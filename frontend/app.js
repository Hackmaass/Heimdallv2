/**
 * Heimdallv2 Tactical Command Center Application Logic
 */

let visualizer = null;
let ws = null;
let activeTracksMap = new Map();
let currentJobId = null;
let pollingInterval = null;

// Initialize when DOM loads
document.addEventListener("DOMContentLoaded", () => {
  visualizer = new TrajectoryMapVisualizer("trajectoryMapCanvas");

  window.onTrackSelected = (trackId) => {
    selectTrack(trackId);
  };

  connectWebSocket();
  initEventListeners();
  loadInitialTelemetry();
  loadCalibrationStatus();
  loadSessionTrajectories();
});

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/tracking`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    document.getElementById("wsStatusDot").style.background = "#00FFB2";
    document.getElementById("wsStatusText").textContent = "CONNECTED (REAL-TIME)";
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleLiveFrame(data);
    } catch (e) {
      console.error("WS Parse error:", e);
    }
  };

  ws.onclose = () => {
    document.getElementById("wsStatusDot").style.background = "#F43F5E";
    document.getElementById("wsStatusText").textContent = "OFFLINE (RECONNECTING)";
    setTimeout(connectWebSocket, 2000);
  };
}

function handleLiveFrame(data) {
  // Update Live Video Frame
  if (data.image_b64) {
    const imgEl = document.getElementById("liveVideoCanvas");
    imgEl.src = `data:image/jpeg;base64,${data.image_b64}`;
    // Pass latest aerial frame to 2D trajectory visualizer underlay
    if (visualizer.layerVideoOverlay) {
      visualizer.setBackgroundImage(imgEl);
    }
  }

  // Update Frame HUD
  if (data.frame !== undefined) {
    document.getElementById("hudFrameIdx").textContent = `FRAME: ${data.frame}`;
    document.getElementById("hudTimestamp").textContent = `T: ${data.timestamp}s`;
    document.getElementById("headerFrameCount").textContent = data.frame;
  }

  // Update Telemetry
  if (data.telemetry) {
    updateTelemetryHUD(data.telemetry);
  }

  // Update Trajectory Canvas & Active Tracks
  if (data.tracks) {
    visualizer.updateTracks(data.tracks);
    updateTrackState(data.tracks, data.total_unique);
  }
}

function updateTelemetryHUD(t) {
  document.getElementById("telGps").textContent = `${t.lat.toFixed(4)}, ${t.lng.toFixed(4)}`;
  document.getElementById("telAlt").textContent = `${t.alt.toFixed(1)} m`;
  document.getElementById("telHeading").textContent = `${t.heading.toFixed(0)}°`;
  document.getElementById("telSpeed").textContent = `${t.speed.toFixed(1)} m/s`;
  document.getElementById("telBattery").textContent = `${t.battery.toFixed(0)}%`;
  document.getElementById("telMode").textContent = t.mode || "AUTO";
}

function updateTrackState(tracks, totalUnique) {
  document.getElementById("headerActiveCount").textContent = tracks.length;
  document.getElementById("headerTotalUnique").textContent = totalUnique || tracks.length;

  // Class Counts
  const counts = { CAR: 0, MOTORCYCLE: 0, BUS: 0, HGV: 0, LGV: 0, PERSON: 0, BICYCLE: 0, OTHER_VEHICLE: 0 };
  for (const t of tracks) {
    if (counts[t.class] !== undefined) counts[t.class]++;
    else counts.OTHER_VEHICLE++;
  }

  document.getElementById("countCars").textContent = counts.CAR;
  document.getElementById("countBikes").textContent = counts.MOTORCYCLE;
  document.getElementById("countBuses").textContent = counts.BUS;
  document.getElementById("countHgv").textContent = counts.HGV;
  document.getElementById("countLgv").textContent = counts.LGV;
  document.getElementById("countPedestrians").textContent = counts.PERSON;

  // Render Table Rows
  const tbody = document.getElementById("tracksTableBody");
  tbody.innerHTML = "";

  for (const t of tracks) {
    const tr = document.createElement("tr");
    if (visualizer.selectedTrackId === t.id) tr.classList.add("selected");

    tr.onclick = () => selectTrack(t.id);

    const fineCls = t.fine_grained_class || t.class || "Car";
    const speedStr = (t.velocity_kmh !== undefined && t.velocity_kmh !== null) ? `${t.velocity_kmh} km/h` : `${(t.speed || 0).toFixed(1)} ${t.speed_unit || 'px/s'}`;
    const accelStr = (t.acceleration_mps2 !== undefined && t.acceleration_mps2 !== null) ? `${t.acceleration_mps2 > 0 ? '+' : ''}${t.acceleration_mps2} m/s²` : '--';
    const quality = t.quality_flag || "VALID";

    tr.innerHTML = `
      <td style="font-weight:600; color:#38BDF8;">#${t.id}</td>
      <td><span class="badge" style="background:rgba(56,189,248,0.15);">${t.class}</span></td>
      <td><span class="badge" style="background:rgba(0,229,255,0.15); color:var(--accent-cyan); font-size:10px;">${fineCls}</span></td>
      <td>${Math.round((t.confidence || 0.9) * 100)}%</td>
      <td style="font-weight:600; color:${t.velocity_kmh ? 'var(--accent-lime)' : 'var(--text-primary)'};">${speedStr}</td>
      <td>${accelStr}</td>
      <td>${(t.heading || 0).toFixed(0)}°</td>
      <td>${t.duration || 0}s</td>
      <td><span class="badge ${quality === 'VALID_HIGH_CONFIDENCE' ? 'badge-lime' : 'badge-amber'}" style="font-size:9px;">${quality.replace('UNRELIABLE_', '')}</span></td>
    `;
    tbody.appendChild(tr);
  }
}

function selectTrack(trackId) {
  visualizer.setSelectedTrack(trackId);
  fetch(`/api/tracks/${trackId}`)
    .then(r => r.json())
    .then(data => {
      document.getElementById("inspectorCard").style.display = "block";
      document.getElementById("inspId").textContent = `#${data.track_id}`;
      document.getElementById("inspClass").textContent = data.normalized_class;
      if (document.getElementById("inspFineClass")) {
        document.getElementById("inspFineClass").textContent = (data.fine_grained_class || data.normalized_class).toUpperCase();
      }
      const speedStr = (data.current_velocity_kmh !== undefined && data.current_velocity_kmh !== null)
        ? `${data.current_velocity_kmh} km/h (${data.current_velocity_mps || '--'} m/s)`
        : `${data.average_speed} px/s`;
      document.getElementById("inspSpeed").textContent = speedStr;
      if (document.getElementById("inspAccel")) {
        document.getElementById("inspAccel").textContent = (data.current_acceleration_mps2 !== undefined && data.current_acceleration_mps2 !== null)
          ? `${data.current_acceleration_mps2 > 0 ? '+' : ''}${data.current_acceleration_mps2} m/s²`
          : '--';
      }
      if (document.getElementById("inspWorldPos")) {
        document.getElementById("inspWorldPos").textContent = data.current_world_pos
          ? `(${data.current_world_pos[0]}m, ${data.current_world_pos[1]}m)`
          : '--';
      }
      if (document.getElementById("inspQuality")) {
        document.getElementById("inspQuality").textContent = (data.quality_flag || "VALID").replace("UNRELIABLE_", "");
      }
      document.getElementById("inspDist").textContent = data.total_distance_meters
        ? `${data.total_distance_meters.toFixed(1)} m`
        : `${data.total_distance_px} px`;
      document.getElementById("inspFrames").textContent = data.total_frames;
      document.getElementById("inspDuration").textContent = `${(data.last_seen - data.first_seen).toFixed(1)}s`;
    })
    .catch(() => {});
}

// State for video selection & processing
let selectedVideoPath = null;
let selectedVideoDuration = null;
let selectedVideoFps = 30.0;

function initEventListeners() {
  document.getElementById("btnOpenProcess").onclick = () => {
    document.getElementById("processModal").classList.add("open");
    loadAvailableVideos();
  };

  document.getElementById("btnCloseModal").onclick = () => {
    document.getElementById("processModal").classList.remove("open");
  };

  document.getElementById("btnCloseCompleteModal").onclick = () => {
    document.getElementById("processModal").classList.remove("open");
  };

  document.getElementById("btnStartProcessing").onclick = () => {
    startProcessingJob();
  };

  // Calibration modal handlers
  const btnOpenCalib = document.getElementById("btnOpenCalib");
  if (btnOpenCalib) {
    btnOpenCalib.onclick = () => {
      document.getElementById("calibModal").classList.add("open");
      loadCalibrationStatus();
    };
  }

  const btnCloseCalib = document.getElementById("btnCloseCalibModal");
  if (btnCloseCalib) {
    btnCloseCalib.onclick = () => {
      document.getElementById("calibModal").classList.remove("open");
    };
  }

  const btnCancelCalib = document.getElementById("btnCancelCalib");
  if (btnCancelCalib) {
    btnCancelCalib.onclick = () => {
      document.getElementById("calibModal").classList.remove("open");
    };
  }

  const btnSaveCalib = document.getElementById("btnSaveCalib");
  if (btnSaveCalib) {
    btnSaveCalib.onclick = async () => {
      const widthM = parseFloat(document.getElementById("calibWidthM").value) || 7.5;
      const lengthM = parseFloat(document.getElementById("calibLengthM").value) || 25.0;
      const pts = (visualizer && visualizer.calibPoints) ? visualizer.calibPoints : [];
      if (pts.length < 4) {
        alert("Please click 4 road corner points on the 2D canvas map first.");
        return;
      }
      try {
        const res = await fetch("/api/calibration", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            image_points: pts,
            road_width_m: widthM,
            road_length_m: lengthM,
          }),
        });
        const data = await res.json();
        if (res.ok) {
          alert(`Ground calibration saved successfully! (RMS Error: ${data.rms_error_m}m)`);
          document.getElementById("calibModal").classList.remove("open");
          loadCalibrationStatus();
        } else {
          alert(data.detail || "Calibration failed.");
        }
      } catch (e) {
        alert("Error saving calibration: " + e);
      }
    };
  }

  const btnClearCalib = document.getElementById("btnClearCalib");
  if (btnClearCalib) {
    btnClearCalib.onclick = async () => {
      try {
        await fetch("/api/calibration", { method: "DELETE" });
        if (visualizer) visualizer.calibPoints = [];
        loadCalibrationStatus();
        alert("Calibration cleared. Reverted to relative kinematics.");
      } catch (e) {}
    };
  }

  document.getElementById("btnResetView").onclick = async () => {
    // 1. Clear 2D canvas visualizer & trails
    visualizer.clear();

    // 2. Clear backend database & in-memory engine trajectories
    try {
      await fetch("/api/trajectories", { method: "DELETE" });
    } catch (e) {
      console.warn("Failed to clear backend trajectories:", e);
    }

    // 3. Reset live telemetry road user counters
    document.getElementById("countCars").textContent = "0";
    document.getElementById("countBikes").textContent = "0";
    document.getElementById("countBuses").textContent = "0";
    document.getElementById("countHgv").textContent = "0";
    document.getElementById("countLgv").textContent = "0";
    document.getElementById("countPedestrians").textContent = "0";

    // 4. Clear table and hide inspector card
    document.getElementById("tracksTableBody").innerHTML = "";
    const inspector = document.getElementById("inspectorCard");
    if (inspector) inspector.style.display = "none";
  };

  document.getElementById("btnAutoFit").onclick = () => {
    visualizer.autoFit();
  };

  document.getElementById("btnReloadTrajectories").onclick = () => {
    loadSessionTrajectories();
  };

  // Video Mode Switcher (Live vs Player)
  const btnLive = document.getElementById("btnModeLive");
  const btnPlayer = document.getElementById("btnModePlayer");
  const liveImg = document.getElementById("liveVideoCanvas");
  const videoEl = document.getElementById("annotatedVideoPlayer");
  const playerBar = document.getElementById("playerSelectorBar");

  btnLive.onclick = () => {
    btnLive.classList.add("active");
    btnPlayer.classList.remove("active");
    liveImg.style.display = "block";
    videoEl.style.display = "none";
    playerBar.style.display = "none";
    videoEl.pause();
  };

  btnPlayer.onclick = () => {
    btnPlayer.classList.add("active");
    btnLive.classList.remove("active");
    liveImg.style.display = "none";
    videoEl.style.display = "block";
    playerBar.style.display = "flex";
    loadAvailableOutputVideos();
  };

  // Output Video Selector in Player
  document.getElementById("selectOutputVideo").onchange = (e) => {
    const val = e.target.value;
    if (val) {
      videoEl.setAttribute("src", val);
      videoEl.load();
      videoEl.play().catch(err => console.log("Video playback:", err));
    }
  };

  videoEl.onerror = (e) => {
    console.error("Video player error event:", e, videoEl.error);
  };

  document.getElementById("btnRefreshOutputs").onclick = () => {
    loadAvailableOutputVideos();
  };

  // Pin Current Frame to 2D Map Underlay
  document.getElementById("btnPinFrameToMap").onclick = () => {
    visualizer.setBackgroundImage(liveImg);
    visualizer.layerVideoOverlay = true;
    document.getElementById("layerToggleVideo").classList.add("active");
    visualizer.autoFit();
  };

  // ── Analytical Layer Toggles ──────────────────────────────────────────────
  const toggleLayerBtn = (btnId, layerName) => {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.onclick = () => {
      const isActive = btn.classList.toggle("active");
      visualizer.toggleLayer(layerName, isActive);
    };
  };

  toggleLayerBtn("layerToggleVideo", "video");
  toggleLayerBtn("layerToggleTrails", "trails");
  toggleLayerBtn("layerToggleHeatmap", "heatmap");
  toggleLayerBtn("layerToggleSpeed", "speed");
  toggleLayerBtn("layerToggleConflicts", "conflicts");
  toggleLayerBtn("layerToggleArrows", "arrows");

  // Video Opacity Slider
  const opacitySlider = document.getElementById("sliderVideoOpacity");
  if (opacitySlider) {
    opacitySlider.oninput = (e) => {
      visualizer.setVideoOpacity(parseFloat(e.target.value));
    };
  }

  // Class Filter Badges
  document.querySelectorAll(".class-chip").forEach(chip => {
    chip.onclick = () => {
      const cls = chip.getAttribute("data-class");
      if (cls === "ALL") {
        document.querySelectorAll(".class-chip").forEach(c => c.classList.remove("active"));
        chip.classList.add("active");
        visualizer.clearClassFilters();
      } else {
        document.querySelector('.class-chip[data-class="ALL"]').classList.remove("active");
        const isActive = chip.classList.toggle("active");
        visualizer.setClassFilter(cls, isActive);

        // If none active, reset to ALL
        const activeCount = document.querySelectorAll('.class-chip.active:not([data-class="ALL"])').length;
        if (activeCount === 0) {
          document.querySelector('.class-chip[data-class="ALL"]').classList.add("active");
          visualizer.clearClassFilters();
        }
      }
    };
  });

  // Video Source Tab Switching
  const tabUpload = document.getElementById("tabUpload");
  const tabExisting = document.getElementById("tabExisting");
  const paneUpload = document.getElementById("paneUpload");
  const paneExisting = document.getElementById("paneExisting");

  tabUpload.onclick = () => {
    tabUpload.classList.add("active");
    tabExisting.classList.remove("active");
    paneUpload.style.display = "block";
    paneExisting.style.display = "none";
  };

  tabExisting.onclick = () => {
    tabExisting.classList.add("active");
    tabUpload.classList.remove("active");
    paneExisting.style.display = "block";
    paneUpload.style.display = "none";
    loadAvailableVideos();
  };

  // Video File Upload Drag & Drop
  const dropzone = document.getElementById("uploadDropzone");
  const fileInput = document.getElementById("videoFileInput");

  dropzone.onclick = () => fileInput.click();

  dropzone.ondragover = (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  };

  dropzone.ondragleave = () => {
    dropzone.classList.remove("dragover");
  };

  dropzone.ondrop = (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  fileInput.onchange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileUpload(e.target.files[0]);
    }
  };

  // Server Existing Video Select
  document.getElementById("selectExistingVideo").onchange = (e) => {
    const select = e.target;
    const opt = select.options[select.selectedIndex];
    if (opt && opt.value) {
      selectedVideoPath = opt.value;
      const dur = parseFloat(opt.getAttribute("data-dur")) || null;
      const fps = parseFloat(opt.getAttribute("data-fps")) || 30;
      const size = opt.getAttribute("data-size") || "";
      const res = opt.getAttribute("data-res") || "";
      selectedVideoDuration = dur;
      selectedVideoFps = fps;

      showSelectedVideoCard(opt.text.split(" (")[0], `${size} MB | ${dur ? dur + "s" : ""} | ${fps} FPS | ${res}`);
    }
  };

  // Duration Mode Radio Controls
  const radioFull = document.getElementById("radioFullVideo");
  const radioLimit = document.getElementById("radioLimitDuration");
  const timeControls = document.getElementById("timeLimitControls");
  const durationHint = document.getElementById("durationHint");

  const updateDurationUI = () => {
    if (radioLimit.checked) {
      timeControls.style.display = "block";
      const sec = parseFloat(document.getElementById("inputDuration").value) || 10;
      durationHint.textContent = `Limit to ${sec}s`;
    } else {
      timeControls.style.display = "none";
      durationHint.textContent = selectedVideoDuration ? `Full Video (${selectedVideoDuration}s)` : "Full Video";
    }
  };

  radioFull.onchange = updateDurationUI;
  radioLimit.onchange = updateDurationUI;

  document.getElementById("inputDuration").oninput = (e) => {
    const sec = parseFloat(e.target.value) || 0;
    durationHint.textContent = `Limit to ${sec}s`;
    // Update active preset button highlight
    document.querySelectorAll(".preset-btn").forEach(btn => {
      btn.classList.toggle("active", parseFloat(btn.getAttribute("data-sec")) === sec);
    });
  };

  // Duration Preset Buttons
  document.querySelectorAll(".preset-btn").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const sec = parseFloat(btn.getAttribute("data-sec"));
      document.getElementById("inputDuration").value = sec;
      radioLimit.checked = true;
      updateDurationUI();
    };
  });

  // SAHI Toggle — show/hide slice size options
  const sahiCheckbox = document.getElementById("checkEnableSAHI");
  const sahiOptions = document.getElementById("sahiOptions");
  if (sahiCheckbox && sahiOptions) {
    sahiCheckbox.onchange = () => {
      sahiOptions.style.display = sahiCheckbox.checked ? "block" : "none";
    };
  }
}

async function handleFileUpload(file) {
  const dropText = document.getElementById("uploadDropText");
  dropText.textContent = `Uploading ${file.name}...`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/video/upload", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) throw new Error("Upload failed: " + res.statusText);

    const data = await res.json();
    selectedVideoPath = data.saved_path;
    selectedVideoDuration = data.duration_seconds;
    selectedVideoFps = data.fps || 30.0;

    dropText.textContent = `Uploaded: ${file.name}`;
    showSelectedVideoCard(
      data.original_filename,
      `${data.size_mb} MB | ${data.duration_seconds ? data.duration_seconds + "s" : ""} | ${data.fps || 30} FPS | ${data.resolution || ""}`
    );
  } catch (err) {
    alert("Video upload error: " + err.message);
    dropText.textContent = "Click or Drag & Drop Aerial Drone Video Here";
  }
}

async function loadAvailableVideos() {
  try {
    const res = await fetch("/api/videos");
    const data = await res.json();
    const select = document.getElementById("selectExistingVideo");
    select.innerHTML = '<option value="">-- Choose a video from data/ repository --</option>';

    for (const v of data.videos) {
      const opt = document.createElement("option");
      opt.value = v.path;
      opt.setAttribute("data-dur", v.duration_seconds || "");
      opt.setAttribute("data-fps", v.fps || 30);
      opt.setAttribute("data-size", v.size_mb || "");
      opt.setAttribute("data-res", v.resolution || "");
      opt.textContent = `${v.filename} (${v.size_mb} MB, ${v.duration_seconds ? v.duration_seconds + "s" : "N/A"})`;
      select.appendChild(opt);
    }

    // Default select first video if none selected
    if (!selectedVideoPath && data.videos.length > 0) {
      select.selectedIndex = 1;
      select.dispatchEvent(new Event("change"));
    }
  } catch (err) {
    console.error("Failed to load videos:", err);
  }
}

function showSelectedVideoCard(name, metaText) {
  const card = document.getElementById("selectedVideoCard");
  card.style.display = "flex";
  document.getElementById("selectedVideoName").textContent = name;
  document.getElementById("selectedVideoMeta").textContent = metaText;

  if (document.getElementById("radioFullVideo").checked) {
    document.getElementById("durationHint").textContent = selectedVideoDuration ? `Full Video (${selectedVideoDuration}s)` : "Full Video";
  }
}

async function startProcessingJob() {
  const model = document.getElementById("selectModel").value;
  const tracker = document.getElementById("selectTracker").value;
  const conf = parseFloat(document.getElementById("inputConf").value) || 0.25;
  const frameStep = parseInt(document.getElementById("selectFrameStep").value) || 1;
  const saveVideo = document.getElementById("checkSaveVideo").checked;
  const enableSahi = document.getElementById("checkEnableSAHI").checked;
  const sahiSliceSize = parseInt(document.getElementById("selectSAHISliceSize").value) || 960;

  const isLimit = document.getElementById("radioLimitDuration").checked;
  const durationSec = isLimit ? (parseFloat(document.getElementById("inputDuration").value) || null) : null;
  const startOffsetSec = isLimit ? (parseFloat(document.getElementById("inputStartOffset").value) || 0.0) : 0.0;

  const btn = document.getElementById("btnStartProcessing");
  btn.disabled = true;
  btn.textContent = "Launching Pipeline...";

  try {
    const payload = {
      video_path: selectedVideoPath,
      model_name: model,
      tracker_type: tracker,
      confidence_threshold: conf,
      process_every_n_frames: frameStep,
      save_annotated_video: saveVideo,
      duration_seconds: durationSec,
      start_seconds: startOffsetSec,
      enable_sahi: enableSahi,
      sahi_slice_size: sahiSliceSize,
    };

    const res = await fetch("/api/video/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to start pipeline");
    }

    const data = await res.json();
    currentJobId = data.video_id;

    // Switch to progress view
    document.getElementById("modalForm").style.display = "none";
    document.getElementById("modalProgress").style.display = "block";
    document.getElementById("modalCompleteActions").style.display = "none";

    pollJobStatus(currentJobId);
  } catch (e) {
    alert("Failed to start processing: " + e.message);
    btn.disabled = false;
    btn.textContent = "Launch Pipeline";
  }
}

function pollJobStatus(jobId) {
  if (pollingInterval) clearInterval(pollingInterval);

  pollingInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/video/${jobId}/status`);
      const data = await res.json();

      document.getElementById("progressPercent").textContent = `${data.progress_percent}%`;
      document.getElementById("progressBarFill").style.width = `${data.progress_percent}%`;
      document.getElementById("progressStatusText").textContent = `STATUS: ${data.status} | FPS: ${data.fps_processing} | FRAME: ${data.current_frame}/${data.total_frames} | ACTIVE: ${data.active_tracks} | UNIQUE: ${data.total_unique_tracks}`;

      if (data.status === "COMPLETED") {
        clearInterval(pollingInterval);
        document.getElementById("progressStatusText").textContent = `✓ COMPLETED: ${data.total_unique_tracks} Road Users Detected across ${data.current_frame} frames!`;

        // Setup output download buttons
        if (data.output_files) {
          const dlVideo = document.getElementById("downloadAnnotatedVideo");
          const dlCsv = document.getElementById("downloadTracksCsv");
          const dlTraj = document.getElementById("downloadTrajJson");
          const dlSummary = document.getElementById("downloadSummaryJson");

          if (data.output_files.annotated_video) {
            const videoSrc = `/api/outputs/${data.output_files.annotated_video.split(/[\\/]/).pop()}`;
            dlVideo.href = videoSrc;
            dlVideo.style.display = "flex";
            document.getElementById("annotatedVideoPlayer").src = videoSrc;
          } else {
            dlVideo.style.display = "none";
          }

          if (data.output_files.tracks_csv) {
            dlCsv.href = `/api/outputs/${data.output_files.tracks_csv.split(/[\\/]/).pop()}`;
          }
          if (data.output_files.trajectories_json) {
            dlTraj.href = `/api/outputs/${data.output_files.trajectories_json.split(/[\\/]/).pop()}`;
          }
          if (data.output_files.summary_json) {
            dlSummary.href = `/api/outputs/${data.output_files.summary_json.split(/[\\/]/).pop()}`;
          }
        }

        document.getElementById("modalCompleteActions").style.display = "block";

        // Load the freshly completed full trajectories onto the 2D canvas & table
        loadSessionTrajectories();

        // Reset start button
        const btn = document.getElementById("btnStartProcessing");
        btn.disabled = false;
        btn.textContent = "Launch Pipeline";

      } else if (data.status === "FAILED") {
        clearInterval(pollingInterval);
        document.getElementById("progressStatusText").textContent = `FAILED: ${data.error_message}`;
        alert("Pipeline failed: " + data.error_message);
        document.getElementById("modalForm").style.display = "block";
        document.getElementById("modalProgress").style.display = "none";
        const btn = document.getElementById("btnStartProcessing");
        btn.disabled = false;
        btn.textContent = "Launch Pipeline";
      }
    } catch (e) {
      console.error("Poll status error:", e);
    }
  }, 400);
}

async function loadSessionTrajectories() {
  try {
    const res = await fetch("/api/trajectories");
    const data = await res.json();
    if (data.trajectories && data.trajectories.length > 0) {
      visualizer.loadFullTrajectories(data.trajectories);
      updateTrackState(data.trajectories, data.total);
    }
  } catch (err) {
    console.warn("Could not load session trajectories:", err);
  }
}

async function loadAvailableOutputVideos() {
  try {
    const res = await fetch("/api/outputs");
    const data = await res.json();
    const select = document.getElementById("selectOutputVideo");
    select.innerHTML = '<option value="">-- Choose a recorded video run --</option>';

    if (data.outputs && data.outputs.length > 0) {
      for (const out of data.outputs) {
        const opt = document.createElement("option");
        opt.value = out.url;
        opt.textContent = `${out.filename} (${out.size_mb} MB)`;
        select.appendChild(opt);
      }

      // If video player has no src, load first output
      const videoEl = document.getElementById("annotatedVideoPlayer");
      if (!videoEl.getAttribute("src") && data.outputs.length > 0) {
        select.selectedIndex = 1;
        videoEl.setAttribute("src", data.outputs[0].url);
        videoEl.load();
      }
    } else {
      select.innerHTML = '<option value="">No recorded video runs available yet</option>';
    }
  } catch (err) {
    console.error("Failed to load output videos:", err);
  }
}

function loadInitialTelemetry() {
  fetch("/api/telemetry")
    .then(r => r.json())
    .then(t => updateTelemetryHUD(t))
    .catch(() => {});
}

async function loadCalibrationStatus() {
  try {
    const res = await fetch("/api/calibration");
    const data = await res.json();
    const badge = document.getElementById("headerCalibStatus");
    if (!badge) return;

    if (data.is_calibrated) {
      badge.textContent = `CALIBRATED (RMS: ${data.rms_error_m}m)`;
      badge.style.color = "var(--accent-lime)";
    } else if (data.has_srt_telemetry) {
      badge.textContent = `SRT TELEMETRY (${data.telemetry_altitude_m || 70.5}m AGL)`;
      badge.style.color = "var(--accent-cyan)";
    } else {
      badge.textContent = "UNCALIBRATED (px/s)";
      badge.style.color = "var(--accent-amber)";
    }
  } catch (e) {}
}
