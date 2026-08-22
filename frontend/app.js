/**
 * Heimdallv2 Tactical Command Center Application Logic
 */

let visualizer = null;
let ws = null;
let activeTracksMap = new Map();
let currentJobId = null;
let pollingInterval = null;

// Level Navigation & Filter State
let currentActiveLevel = 3; // Default to Level 3 Aggregate mode
let l3TimeRange = "all";
let l3LaneFilter = null;
let l3MovementFilter = null;
let l3OriginFilter = null;
let l3DestFilter = null;
let lastL3RefreshTime = 0;

// Initialize when DOM loads
document.addEventListener("DOMContentLoaded", () => {
  visualizer = new TrajectoryMapVisualizer("trajectoryMapCanvas");

  window.onTrackSelected = (trackId) => {
    selectTrack(trackId);
  };

  connectWebSocket();
  initEventListeners();
  initResizableLayout();
  initLevel3UI();
  loadInitialTelemetry();
  loadCalibrationStatus();
  loadSessionTrajectories();
  refreshLevel3Analytics();
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

    if (currentActiveLevel === 3) {
      const now = Date.now();
      if (now - lastL3RefreshTime > 2500) {
        lastL3RefreshTime = now;
        refreshLevel3Analytics();
      }
    }
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
    const velKmh = (t.velocity_kmh !== undefined && t.velocity_kmh !== null)
      ? Number(t.velocity_kmh)
      : (t.speed ? Number((t.speed * 0.234).toFixed(1)) : 0.0);
    const accelVal = (t.acceleration_mps2 !== undefined && t.acceleration_mps2 !== null)
      ? Number(t.acceleration_mps2)
      : ((t.accel_mps2 !== undefined && t.accel_mps2 !== null) ? Number(t.accel_mps2) : 0.0);

    const speedStr = `${velKmh.toFixed(1)} km/h`;
    const accelStr = `${accelVal >= 0 ? '+' : ''}${accelVal.toFixed(2)} m/s²`;
    const quality = t.quality_flag || "VALID";

    tr.innerHTML = `
      <td style="font-weight:600; color:#38BDF8;">#${t.id}</td>
      <td><span class="badge" style="background:rgba(56,189,248,0.15);">${t.class}</span></td>
      <td><span class="badge" style="background:rgba(0,229,255,0.15); color:var(--accent-cyan); font-size:10px;">${fineCls}</span></td>
      <td>${Math.round((t.confidence || 0.9) * 100)}%</td>
      <td style="font-weight:600; color:var(--accent-lime);">${speedStr}</td>
      <td style="font-weight:500; color:${accelVal < 0 ? '#F43F5E' : (accelVal > 0 ? '#38BDF8' : 'var(--text-secondary)')};">${accelStr}</td>
      <td>${(t.heading || 0).toFixed(0)}°</td>
      <td>${t.duration || 0}s</td>
      <td><span class="badge ${quality.includes('VALID') ? 'badge-lime' : 'badge-amber'}" style="font-size:9px;">${quality.replace('UNRELIABLE_', '')}</span></td>
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
      const velKmh = (data.current_velocity_kmh !== undefined && data.current_velocity_kmh !== null)
        ? Number(data.current_velocity_kmh)
        : (data.average_speed ? Number((data.average_speed * 0.234).toFixed(1)) : 0.0);
      const velMps = (data.current_velocity_mps !== undefined && data.current_velocity_mps !== null)
        ? Number(data.current_velocity_mps)
        : Number((velKmh / 3.6).toFixed(2));
      document.getElementById("inspSpeed").textContent = `${velKmh.toFixed(1)} km/h (${velMps.toFixed(2)} m/s)`;

      const accelVal = (data.current_acceleration_mps2 !== undefined && data.current_acceleration_mps2 !== null)
        ? Number(data.current_acceleration_mps2)
        : 0.0;
      if (document.getElementById("inspAccel")) {
        document.getElementById("inspAccel").textContent = `${accelVal >= 0 ? '+' : ''}${accelVal.toFixed(2)} m/s²`;
        document.getElementById("inspAccel").style.color = accelVal < 0 ? '#F43F5E' : (accelVal > 0 ? '#38BDF8' : 'var(--text-primary)');
      }
      if (document.getElementById("inspWorldPos")) {
        document.getElementById("inspWorldPos").textContent = data.current_world_pos
          ? `(${Number(data.current_world_pos[0]).toFixed(1)}m, ${Number(data.current_world_pos[1]).toFixed(1)}m)`
          : (data.total_distance_meters ? `(${Number(data.total_distance_meters).toFixed(1)}m travelled)` : '--');
      }
      if (document.getElementById("inspQuality")) {
        document.getElementById("inspQuality").textContent = (data.quality_flag || "VALID").replace("UNRELIABLE_", "");
      }
      document.getElementById("inspDist").textContent = data.total_distance_meters
        ? `${Number(data.total_distance_meters).toFixed(1)} m`
        : `${(Number(data.total_distance_px || 0) * 0.065).toFixed(1)} m`;
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

/* ==============================================================================
   INTERACTIVE RESIZABLE WORKSPACE LAYOUT (HORIZONTAL & VERTICAL SPLITTERS)
============================================================================== */

function initResizableLayout() {
  const gutterCol2 = document.getElementById("gutterCol2");
  const panelSidebar = document.getElementById("panelSidebar");
  const workspaceTopRow = document.getElementById("workspaceTopRow");

  const gutterCol1 = document.getElementById("gutterCol1");
  const panelVideo = document.getElementById("panelVideo");
  const panelMap = document.getElementById("panelMap");

  const gutterRow = document.getElementById("gutterRow");
  const panelBottom = document.getElementById("panelBottom");

  // Restore persistent saved panel dimensions if available
  try {
    const savedSidebarWidth = localStorage.getItem("heimdall_sidebar_width");
    if (savedSidebarWidth && panelSidebar) {
      panelSidebar.style.width = `${Math.max(260, Math.min(850, parseInt(savedSidebarWidth)))}px`;
    }
    const savedVideoPct = localStorage.getItem("heimdall_video_pct");
    if (savedVideoPct && panelVideo && panelMap) {
      panelVideo.style.flex = `0 0 ${savedVideoPct}%`;
      panelMap.style.flex = `1 1 auto`;
    }
    const savedBottomHeight = localStorage.getItem("heimdall_bottom_height");
    if (savedBottomHeight && panelBottom) {
      panelBottom.style.height = `${Math.max(70, Math.min(550, parseInt(savedBottomHeight)))}px`;
    }
  } catch (e) {}

  // 1. Right Sidebar Horizontal Resizer (gutterCol2)
  if (gutterCol2 && panelSidebar) {
    let isDragging = false;
    let startX = 0;
    let startWidth = 380;

    gutterCol2.addEventListener("mousedown", (e) => {
      isDragging = true;
      startX = e.clientX;
      startWidth = panelSidebar.getBoundingClientRect().width;
      gutterCol2.classList.add("active");
      document.body.classList.add("resizing-col");
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const deltaX = startX - e.clientX; // Dragging left increases width, dragging right decreases
      const newWidth = Math.max(260, Math.min(850, startWidth + deltaX));
      panelSidebar.style.width = `${newWidth}px`;
      if (visualizer) visualizer.resize();
    });

    window.addEventListener("mouseup", () => {
      if (isDragging) {
        isDragging = false;
        gutterCol2.classList.remove("active");
        document.body.classList.remove("resizing-col");
        try {
          localStorage.setItem("heimdall_sidebar_width", Math.round(panelSidebar.getBoundingClientRect().width));
        } catch (e) {}
        if (visualizer) visualizer.resize();
      }
    });
  }

  // 2. Video vs Map Horizontal Resizer (gutterCol1)
  if (gutterCol1 && panelVideo && panelMap && workspaceTopRow) {
    let isDragging = false;
    let startX = 0;
    let startVideoWidth = 0;

    gutterCol1.addEventListener("mousedown", (e) => {
      isDragging = true;
      startX = e.clientX;
      startVideoWidth = panelVideo.getBoundingClientRect().width;
      gutterCol1.classList.add("active");
      document.body.classList.add("resizing-col");
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const deltaX = e.clientX - startX;
      const sidebarWidth = panelSidebar ? panelSidebar.getBoundingClientRect().width : 380;
      const availableWidth = workspaceTopRow.getBoundingClientRect().width - sidebarWidth - 14;
      const newVideoWidth = Math.max(220, Math.min(availableWidth - 220, startVideoWidth + deltaX));
      const videoPct = (newVideoWidth / availableWidth) * 100;
      panelVideo.style.flex = `0 0 ${videoPct}%`;
      panelMap.style.flex = `1 1 auto`;
      if (visualizer) visualizer.resize();
    });

    window.addEventListener("mouseup", () => {
      if (isDragging) {
        isDragging = false;
        gutterCol1.classList.remove("active");
        document.body.classList.remove("resizing-col");
        try {
          const sidebarWidth = panelSidebar ? panelSidebar.getBoundingClientRect().width : 380;
          const availableWidth = workspaceTopRow.getBoundingClientRect().width - sidebarWidth - 14;
          const videoPct = (panelVideo.getBoundingClientRect().width / availableWidth) * 100;
          localStorage.setItem("heimdall_video_pct", videoPct.toFixed(1));
        } catch (e) {}
        if (visualizer) visualizer.resize();
      }
    });
  }

  // 3. Bottom Table Vertical Resizer (gutterRow)
  if (gutterRow && panelBottom) {
    let isDragging = false;
    let startY = 0;
    let startHeight = 180;

    gutterRow.addEventListener("mousedown", (e) => {
      isDragging = true;
      startY = e.clientY;
      startHeight = panelBottom.getBoundingClientRect().height;
      gutterRow.classList.add("active");
      document.body.classList.add("resizing-row");
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const deltaY = startY - e.clientY; // Dragging up increases height, dragging down decreases
      const newHeight = Math.max(70, Math.min(550, startHeight + deltaY));
      panelBottom.style.height = `${newHeight}px`;
      if (visualizer) visualizer.resize();
    });

    window.addEventListener("mouseup", () => {
      if (isDragging) {
        isDragging = false;
        gutterRow.classList.remove("active");
        document.body.classList.remove("resizing-row");
        try {
          localStorage.setItem("heimdall_bottom_height", Math.round(panelBottom.getBoundingClientRect().height));
        } catch (e) {}
        if (visualizer) visualizer.resize();
      }
    });
  }
}

/* ==============================================================================
   LEVEL 3 AGGREGATE TRAFFIC INTELLIGENCE CONTROLLER & CHART RENDERERS
============================================================================== */

let currentSidebarTab = "visual"; // "telemetry", "visual", "tabular"

function initLevel3UI() {
  const btnL1 = document.getElementById("btnNavLevel1");
  const btnL2 = document.getElementById("btnNavLevel2");
  const btnL3 = document.getElementById("btnNavLevel3");

  if (btnL1) btnL1.onclick = () => setLevelMode(1);
  if (btnL2) btnL2.onclick = () => setLevelMode(2);
  if (btnL3) btnL3.onclick = () => setLevelMode(3);

  // Sidebar Tab Switchers
  const tabTel = document.getElementById("tabTelemetry");
  const tabVis = document.getElementById("tabL3Visual");
  const tabTab = document.getElementById("tabL3Tabular");

  if (tabTel) tabTel.onclick = () => setSidebarTab("telemetry");
  if (tabVis) tabVis.onclick = () => setSidebarTab("visual");
  if (tabTab) tabTab.onclick = () => setSidebarTab("tabular");

  // Time Range Chips
  document.querySelectorAll(".time-chip").forEach(chip => {
    chip.onclick = () => {
      document.querySelectorAll(".time-chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      l3TimeRange = chip.getAttribute("data-range") || "all";
      refreshLevel3Analytics();
    };
  });

  // Clear Filter Button
  const btnClearFilter = document.getElementById("btnClearL3Filter");
  if (btnClearFilter) {
    btnClearFilter.onclick = () => clearL3Filter();
  }

  // Refresh Analytics Button
  const btnRefresh = document.getElementById("btnRefreshL3");
  if (btnRefresh) {
    btnRefresh.onclick = () => refreshLevel3Analytics();
  }
}

function setSidebarTab(tabName) {
  currentSidebarTab = tabName;
  const tabTel = document.getElementById("tabTelemetry");
  const tabVis = document.getElementById("tabL3Visual");
  const tabTab = document.getElementById("tabL3Tabular");

  const viewTel = document.getElementById("viewSidebarTelemetry");
  const viewVis = document.getElementById("viewSidebarL3Visual");
  const viewTab = document.getElementById("viewSidebarL3Tabular");
  const badge = document.getElementById("sidebarModeBadge");

  if (tabTel) tabTel.classList.toggle("active", tabName === "telemetry");
  if (tabVis) tabVis.classList.toggle("active", tabName === "visual");
  if (tabTab) tabTab.classList.toggle("active", tabName === "tabular");

  if (viewTel) viewTel.style.display = (tabName === "telemetry") ? "flex" : "none";
  if (viewVis) viewVis.style.display = (tabName === "visual") ? "flex" : "none";
  if (viewTab) viewTab.style.display = (tabName === "tabular") ? "flex" : "none";

  if (badge) {
    if (tabName === "telemetry") {
      badge.textContent = "OPERATIONAL";
      badge.style.color = "var(--accent-lime)";
    } else if (tabName === "visual") {
      badge.textContent = "L3 VISUAL";
      badge.style.color = "var(--accent-cyan)";
    } else {
      badge.textContent = "L3 TABULAR";
      badge.style.color = "var(--accent-orange)";
    }
  }

  if (tabName === "visual" || tabName === "tabular") {
    refreshLevel3Analytics();
  }
}

function setLevelMode(level) {
  currentActiveLevel = level;
  const btnL1 = document.getElementById("btnNavLevel1");
  const btnL2 = document.getElementById("btnNavLevel2");
  const btnL3 = document.getElementById("btnNavLevel3");

  if (btnL1) btnL1.classList.toggle("active", level === 1);
  if (btnL2) btnL2.classList.toggle("active", level === 2);
  if (btnL3) btnL3.classList.toggle("active", level === 3);

  if (level === 1 || level === 2) {
    setSidebarTab("telemetry");
  } else {
    setSidebarTab("visual");
  }
}

function applyL3Filter(filterType, filterValue, labelText) {
  l3LaneFilter = (filterType === "lane") ? filterValue : null;
  l3MovementFilter = (filterType === "movement") ? filterValue : null;
  if (filterType === "od") {
    l3OriginFilter = filterValue.origin;
    l3DestFilter = filterValue.dest;
  } else {
    l3OriginFilter = null;
    l3DestFilter = null;
  }

  const badge = document.getElementById("l3ActiveFilterBadge");
  const textEl = document.getElementById("l3FilterText");
  if (badge && textEl) {
    badge.style.display = "inline-flex";
    textEl.textContent = labelText || `${filterType.toUpperCase()}: ${filterValue}`;
  }

  if (visualizer) {
    visualizer.setHighlightFilter({ type: filterType, value: filterValue });
  }

  refreshLevel3Analytics();
}

function clearL3Filter() {
  l3LaneFilter = null;
  l3MovementFilter = null;
  l3OriginFilter = null;
  l3DestFilter = null;

  const badge = document.getElementById("l3ActiveFilterBadge");
  if (badge) badge.style.display = "none";

  if (visualizer) {
    visualizer.clearHighlightFilter();
  }

  refreshLevel3Analytics();
}

async function refreshLevel3Analytics() {
  try {
    const params = new URLSearchParams();
    if (l3TimeRange) params.append("time_range", l3TimeRange);
    if (l3LaneFilter) params.append("lane_id", l3LaneFilter);
    if (l3MovementFilter) params.append("movement", l3MovementFilter);
    if (l3OriginFilter) params.append("origin", l3OriginFilter);
    if (l3DestFilter) params.append("destination", l3DestFilter);

    const res = await fetch(`/api/analytics/level3?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();

    // 1. Update Top 6 KPI Cards
    if (data.kpis) {
      document.getElementById("kpiTotalFlow").textContent = data.kpis.total_flow_vpm.toFixed(1);
      document.getElementById("kpiAvgSpeed").textContent = data.kpis.average_speed_kmh.toFixed(1);
      document.getElementById("kpiDensity").textContent = data.kpis.traffic_density_vpk.toFixed(1);
      document.getElementById("kpiOccupancy").textContent = `${data.kpis.road_occupancy_pct.toFixed(1)}%`;
      document.getElementById("kpiQueue").textContent = data.kpis.active_queue_meters.toFixed(1);
      document.getElementById("kpiPeakFlow").textContent = data.kpis.peak_flow_vpm.toFixed(1);
    }

    // 2. Render Visual Form Charts
    renderFlowTimelineChart(data.flow_timeline);
    renderIntersectionMovements(data.movements);
    renderLaneVolumes(data.lane_volumes);
    renderModalSplit(data.modal_split);
    renderQueueEvolution(data.queue_evolution);
    renderOdMatrix(data.od_matrix);
    renderFlowDensityScatter(data.flow_density);

    // 3. Render Tabular Form Tables
    renderTabularAnalytics(data);

  } catch (err) {
    console.warn("Failed to refresh Level 3 analytics:", err);
  }
}

function renderTabularAnalytics(data) {
  // 1. KPI Summary Table
  const tbodyKpi = document.getElementById("tbodyKpiSummary");
  if (tbodyKpi && data.kpis) {
    tbodyKpi.innerHTML = `
      <tr><td>TOTAL FLOW</td><td style="color:var(--accent-cyan); font-weight:bold;">${data.kpis.total_flow_vpm.toFixed(1)}</td><td>veh/min</td><td><span class="badge badge-cyan">NORMAL</span></td></tr>
      <tr><td>AVERAGE SPEED</td><td style="color:var(--accent-lime); font-weight:bold;">${data.kpis.average_speed_kmh.toFixed(1)}</td><td>km/h</td><td><span class="badge badge-lime">FLOWING</span></td></tr>
      <tr><td>TRAFFIC DENSITY</td><td style="color:var(--accent-blue); font-weight:bold;">${data.kpis.traffic_density_vpk.toFixed(1)}</td><td>veh/km</td><td><span class="badge badge-cyan">${data.kpis.traffic_density_vpk > 50 ? 'HEAVY' : 'MODERATE'}</span></td></tr>
      <tr><td>ROAD OCCUPANCY</td><td style="color:var(--accent-orange); font-weight:bold;">${data.kpis.road_occupancy_pct.toFixed(1)}%</td><td>% surface</td><td><span class="badge badge-orange">${data.kpis.road_occupancy_pct > 20 ? 'HIGH' : 'NOMINAL'}</span></td></tr>
      <tr><td>ACTIVE QUEUE</td><td style="color:var(--accent-crimson); font-weight:bold;">${data.kpis.active_queue_meters.toFixed(1)}</td><td>metres</td><td><span class="badge ${data.kpis.active_queue_meters > 20 ? 'badge-crimson' : 'badge-lime'}">${data.kpis.active_queue_meters > 20 ? 'QUEUEING' : 'FREE'}</span></td></tr>
      <tr><td>PEAK FLOW</td><td style="color:var(--accent-purple); font-weight:bold;">${data.kpis.peak_flow_vpm.toFixed(1)}</td><td>veh/min</td><td><span class="badge badge-cyan">RECORDED</span></td></tr>
    `;
  }

  // 2. Movements Table
  const tbodyMov = document.getElementById("tbodyMovements");
  if (tbodyMov && data.movements) {
    tbodyMov.innerHTML = "";
    data.movements.forEach(m => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.onclick = () => applyL3Filter("movement", m.movement, `MOVEMENT: ${m.movement}`);
      tr.innerHTML = `
        <td style="font-weight:600; color:var(--accent-cyan);">${m.movement}</td>
        <td><strong>${m.count}</strong></td>
        <td style="color:var(--text-secondary);">${m.percentage}%</td>
      `;
      tbodyMov.appendChild(tr);
    });
  }

  // 3. Lanes Table
  const tbodyLanes = document.getElementById("tbodyLanes");
  if (tbodyLanes && data.lane_volumes) {
    tbodyLanes.innerHTML = "";
    data.lane_volumes.forEach(l => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.onclick = () => applyL3Filter("lane", l.lane_id, `LANE: ${l.lane_id}`);
      const s = l.split || { cars: 0, motorcycles: 0 };
      tr.innerHTML = `
        <td style="font-weight:600; color:var(--accent-blue);">${l.lane_id}</td>
        <td><strong>${l.volume}</strong></td>
        <td>${l.flow_vpm}</td>
        <td>${s.cars}C / ${s.motorcycles}B</td>
      `;
      tbodyLanes.appendChild(tr);
    });
  }

  // 4. Modal Breakdown Table
  const tbodyModal = document.getElementById("tbodyModalBreakdown");
  if (tbodyModal && data.modal_split) {
    tbodyModal.innerHTML = "";
    data.modal_split.forEach(s => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span style="color:${s.color}; font-weight:600;">■ ${s.category}</span></td>
        <td><strong>${s.count}</strong></td>
        <td style="color:var(--text-secondary);">${s.percentage}%</td>
      `;
      tbodyModal.appendChild(tr);
    });
  }

  // 5. Origin-Destination Table (Tabular)
  const odTabular = document.getElementById("odMatrixTableTabular");
  if (odTabular && data.od_matrix) {
    renderOdMatrixToTable(odTabular, data.od_matrix);
  }
}

function renderOdMatrixToTable(tableEl, odData) {
  tableEl.innerHTML = "";
  if (!odData || odData.length === 0) {
    tableEl.innerHTML = '<tr><td style="color:var(--text-muted);">No OD movements recorded</td></tr>';
    return;
  }
  const cardinals = ["N", "S", "E", "W"];
  let thead = "<tr><th>O \\ D</th>";
  cardinals.forEach(c => { thead += `<th>${c}</th>`; });
  thead += "</tr>";
  tableEl.innerHTML = thead;

  let maxCount = 1;
  odData.forEach(row => {
    cardinals.forEach(dest => {
      const cell = row.destinations[dest];
      if (cell && cell.count > maxCount) maxCount = cell.count;
    });
  });

  odData.forEach(row => {
    const tr = document.createElement("tr");
    let rowHtml = `<th style="background:rgba(19,31,55,0.8);">${row.origin}</th>`;
    cardinals.forEach(dest => {
      const cell = row.destinations[dest];
      const count = cell ? cell.count : 0;
      const isDiag = (row.origin === dest);
      const isSelected = (l3OriginFilter === row.origin && l3DestFilter === dest);
      const alpha = isDiag ? 0.05 : Math.max(0.1, (count / maxCount) * 0.7);
      const bgStyle = isDiag ? "background:rgba(255,255,255,0.02); color:#64748B;" : `background:rgba(56,189,248,${alpha}); color:var(--text-primary); font-weight:bold;`;
      rowHtml += `<td class="od-cell ${isSelected ? 'active' : ''}" data-orig="${row.origin}" data-dest="${dest}" style="${bgStyle}">${isDiag ? '—' : count}</td>`;
    });
    tr.innerHTML = rowHtml;
    tableEl.appendChild(tr);
  });
}

/* ── 1. Traffic Flow Timeline Chart ────────────────────────────────────────── */
function renderFlowTimelineChart(flowData) {
  const canvas = document.getElementById("flowTimelineCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width || 450;
  canvas.height = rect.height || 140;

  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const bins = (flowData && flowData.bins) ? flowData.bins : [];
  if (bins.length === 0) {
    ctx.fillStyle = "#64748B";
    ctx.font = "11px monospace";
    ctx.textAlign = "center";
    ctx.fillText("No trajectory observations in selected temporal window", w / 2, h / 2);
    return;
  }

  const padLeft = 40;
  const padBottom = 24;
  const padTop = 16;
  const padRight = 16;
  const plotW = w - padLeft - padRight;
  const plotH = h - padTop - padBottom;

  const maxFlow = Math.max(10.0, ...bins.map(b => b.flow_vpm * 1.25));

  // Background Grid Lines
  ctx.strokeStyle = "rgba(56, 189, 248, 0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const yVal = maxFlow * (i / 3);
    const py = padTop + plotH - (plotH * (i / 3));
    ctx.beginPath();
    ctx.moveTo(padLeft, py);
    ctx.lineTo(padLeft + plotW, py);
    ctx.stroke();

    ctx.fillStyle = "#64748B";
    ctx.font = "9px monospace";
    ctx.textAlign = "right";
    ctx.fillText(Math.round(yVal), padLeft - 6, py + 3);
  }

  // Draw Stacked Area Curves
  const stepX = bins.length > 1 ? plotW / (bins.length - 1) : plotW;

  // Draw Area for Total Flow
  ctx.beginPath();
  bins.forEach((b, i) => {
    const px = padLeft + i * stepX;
    const py = padTop + plotH - (plotH * (b.flow_vpm / maxFlow));
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.lineTo(padLeft + (bins.length - 1) * stepX, padTop + plotH);
  ctx.lineTo(padLeft, padTop + plotH);
  ctx.closePath();

  const areaGrad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
  areaGrad.addColorStop(0, "rgba(56, 189, 248, 0.45)");
  areaGrad.addColorStop(1, "rgba(56, 189, 248, 0.02)");
  ctx.fillStyle = areaGrad;
  ctx.fill();

  // Draw Main Line
  ctx.beginPath();
  bins.forEach((b, i) => {
    const px = padLeft + i * stepX;
    const py = padTop + plotH - (plotH * (b.flow_vpm / maxFlow));
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.strokeStyle = "#38BDF8";
  ctx.lineWidth = 2;
  ctx.stroke();

  // Annotate Peak Flow Point
  let peakIdx = 0;
  let peakVal = 0;
  bins.forEach((b, i) => {
    if (b.flow_vpm > peakVal) {
      peakVal = b.flow_vpm;
      peakIdx = i;
    }
  });

  if (peakVal > 0) {
    const peakX = padLeft + peakIdx * stepX;
    const peakY = padTop + plotH - (plotH * (peakVal / maxFlow));

    ctx.fillStyle = "#FB923C";
    ctx.shadowColor = "#FB923C";
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.arc(peakX, peakY, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.fillStyle = "#FB923C";
    ctx.font = "bold 9px monospace";
    ctx.textAlign = "center";
    ctx.fillText(`PEAK: ${peakVal.toFixed(1)} vpm`, peakX, Math.max(12, peakY - 8));
  }

  // X Axis Labels
  ctx.fillStyle = "#64748B";
  ctx.font = "9px monospace";
  ctx.textAlign = "center";
  const stepLabel = Math.max(1, Math.floor(bins.length / 5));
  bins.forEach((b, i) => {
    if (i % stepLabel === 0 || i === bins.length - 1) {
      const px = padLeft + i * stepX;
      ctx.fillText(b.label, px, padTop + plotH + 16);
    }
  });
}

/* ── 2. Intersection Movement Flow ─────────────────────────────────────────── */
function renderIntersectionMovements(movements) {
  const svg = document.getElementById("intersectionSvg");
  const list = document.getElementById("movementListGrid");
  if (!svg || !list) return;

  svg.innerHTML = "";
  list.innerHTML = "";

  if (!movements || movements.length === 0) {
    svg.innerHTML = '<text x="100" y="100" fill="#64748B" font-size="10" text-anchor="middle" font-family="monospace">No Data</text>';
    return;
  }

  // Pre-define 12 standard movement paths in SVG coordinates (200x200 canvas)
  const pathMap = {
    "N → S": "M 92 18 L 92 182",
    "N → W": "M 92 18 Q 92 92 18 92",
    "N → E": "M 92 18 Q 92 108 182 108",
    "S → N": "M 108 182 L 108 18",
    "S → E": "M 108 182 Q 108 108 182 108",
    "S → W": "M 108 182 Q 108 92 18 92",
    "E → W": "M 182 92 L 18 92",
    "E → N": "M 182 92 Q 108 92 108 18",
    "E → S": "M 182 92 Q 92 92 92 182",
    "W → E": "M 18 108 L 182 108",
    "W → S": "M 18 108 Q 92 108 92 182",
    "W → N": "M 18 108 Q 108 108 108 18",
  };

  // 1. Build Base SVG Geometry & Markers
  let svgContent = `
    <defs>
      <marker id="arrow-cyan" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#00E5FF" />
      </marker>
      <marker id="arrow-lime" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="#C8F23A" />
      </marker>
      <marker id="arrow-muted" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="rgba(100, 116, 139, 0.35)" />
      </marker>
      <filter id="glow-cyan" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="2" result="blur" />
        <feComposite in="SourceGraphic" in2="blur" operator="over" />
      </filter>
    </defs>
    <!-- Background Road Layout -->
    <rect x="74" y="10" width="52" height="180" fill="rgba(19, 31, 55, 0.6)" stroke="rgba(56,189,248,0.2)" rx="4"/>
    <rect x="10" y="74" width="180" height="52" fill="rgba(19, 31, 55, 0.6)" stroke="rgba(56,189,248,0.2)" rx="4"/>
    <circle cx="100" cy="100" r="26" fill="rgba(9, 13, 22, 0.85)" stroke="rgba(0,229,255,0.3)" stroke-dasharray="3,3"/>
    <text x="100" y="24" fill="#94A3B8" font-size="9.5" font-family="monospace" text-anchor="middle" font-weight="bold">N</text>
    <text x="100" y="186" fill="#94A3B8" font-size="9.5" font-family="monospace" text-anchor="middle" font-weight="bold">S</text>
    <text x="22" y="103" fill="#94A3B8" font-size="9.5" font-family="monospace" text-anchor="middle" font-weight="bold">W</text>
    <text x="178" y="103" fill="#94A3B8" font-size="9.5" font-family="monospace" text-anchor="middle" font-weight="bold">E</text>
  `;

  const maxCount = Math.max(1, ...movements.map(m => m.count));

  // 2. Draw Movement Vectors
  movements.forEach(m => {
    const dPath = pathMap[m.movement];
    if (!dPath) return;

    const isSelected = (l3MovementFilter === m.movement);
    const hasVolume = m.count > 0;
    const strokeWidth = hasVolume ? Math.max(1.8, Math.min(6.5, 1.8 + (m.count / maxCount) * 4.7)) : 1.0;
    
    let strokeColor = "rgba(100, 116, 139, 0.25)";
    let marker = "url(#arrow-muted)";
    let filterAttr = "";

    if (isSelected) {
      strokeColor = "#C8F23A";
      marker = "url(#arrow-lime)";
      filterAttr = 'filter="url(#glow-cyan)"';
    } else if (hasVolume) {
      const alpha = Math.max(0.4, Math.min(1.0, 0.35 + (m.count / maxCount) * 0.65));
      strokeColor = `rgba(0, 229, 255, ${alpha.toFixed(2)})`;
      marker = "url(#arrow-cyan)";
      if (m.count / maxCount > 0.35) filterAttr = 'filter="url(#glow-cyan)"';
    }

    svgContent += `
      <path id="svgMov_${m.movement.replace(/[\s→]+/g, '_')}" d="${dPath}" 
            stroke="${strokeColor}" stroke-width="${strokeWidth}" 
            stroke-linecap="round" fill="none" 
            marker-end="${marker}" ${filterAttr}
            style="cursor:pointer; transition:all 0.2s;"
            onclick="applyL3Filter('movement', '${m.movement}', 'MOVEMENT: ${m.movement}')">
        <title>${m.movement}: ${m.count} vehicles (${m.percentage}%)</title>
      </path>
    `;

    // Populate List Items
    const item = document.createElement("div");
    item.className = "movement-item";
    if (isSelected) item.classList.add("active");
    item.onclick = () => {
      if (l3MovementFilter === m.movement) clearL3Filter();
      else applyL3Filter("movement", m.movement, `MOVEMENT: ${m.movement}`);
    };

    item.innerHTML = `
      <span style="color:${hasVolume ? 'var(--text-primary)' : 'var(--text-muted)'}; font-weight:600;">${m.movement}</span>
      <span class="badge" style="background:${hasVolume ? 'rgba(56,189,248,0.15)' : 'transparent'}; color:${hasVolume ? 'var(--accent-cyan)' : 'var(--text-muted)'}; font-size:9px;">${m.count} (${m.percentage}%)</span>
    `;
    list.appendChild(item);
  });

  svg.innerHTML = svgContent;
}

/* ── 3. Lane Volume Breakdown ──────────────────────────────────────────────── */
function renderLaneVolumes(laneData) {
  const container = document.getElementById("laneVolumeList");
  if (!container) return;
  container.innerHTML = "";

  if (!laneData || laneData.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted); font-size:11px; text-align:center; padding:20px;">No lane configurations available</div>';
    return;
  }

  const maxVol = Math.max(1, ...laneData.map(l => l.volume));

  laneData.forEach(lane => {
    const item = document.createElement("div");
    item.className = "lane-bar-item";
    if (l3LaneFilter === lane.lane_id) item.classList.add("active");

    item.onclick = () => {
      if (l3LaneFilter === lane.lane_id) clearL3Filter();
      else applyL3Filter("lane", lane.lane_id, `LANE: ${lane.lane_id}`);
    };

    const pct = Math.round((lane.volume / maxVol) * 100);
    const split = lane.split || { cars: 0, motorcycles: 0, heavy: 0, other: 0 };
    const sTotal = lane.volume || 1;

    item.innerHTML = `
      <div class="lane-bar-header">
        <span style="font-weight:700; color:var(--accent-cyan);">${lane.lane_id}</span>
        <span><strong style="color:var(--accent-lime);">${lane.volume} veh</strong> (${lane.flow_vpm} vpm)</span>
      </div>
      <div class="lane-bar-track" style="width:100%;">
        <div class="lane-bar-fill" style="width:${pct}%; display:flex; border-radius:3px; overflow:hidden;">
          <div style="width:${(split.cars / sTotal) * 100}%; background:#38BDF8;" title="Cars: ${split.cars}"></div>
          <div style="width:${(split.motorcycles / sTotal) * 100}%; background:#C8F23A;" title="Bikes: ${split.motorcycles}"></div>
          <div style="width:${(split.heavy / sTotal) * 100}%; background:#F43F5E;" title="Heavy: ${split.heavy}"></div>
          <div style="width:${(split.other / sTotal) * 100}%; background:#A855F7;" title="Other: ${split.other}"></div>
        </div>
      </div>
    `;
    container.appendChild(item);
  });
}

/* ── 4. Modal Split Donut & List ───────────────────────────────────────────── */
function renderModalSplit(splitData) {
  const canvas = document.getElementById("modalDonutCanvas");
  const list = document.getElementById("modalSplitList");
  if (!canvas || !list) return;

  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  list.innerHTML = "";

  if (!splitData || splitData.length === 0) {
    list.innerHTML = '<span style="color:var(--text-muted);">No data</span>';
    return;
  }

  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  const radius = 34;
  const innerRadius = 22;

  let startAngle = -Math.PI / 2;
  const total = splitData.reduce((acc, s) => acc + s.count, 0) || 1;

  splitData.forEach(s => {
    const sliceAngle = (s.count / total) * Math.PI * 2;
    const endAngle = startAngle + sliceAngle;

    if (s.count > 0) {
      ctx.beginPath();
      ctx.arc(cx, cy, radius, startAngle, endAngle);
      ctx.arc(cx, cy, innerRadius, endAngle, startAngle, true);
      ctx.closePath();
      ctx.fillStyle = s.color || "#38BDF8";
      ctx.fill();
    }

    startAngle = endAngle;

    // List item
    const item = document.createElement("div");
    item.style.display = "flex";
    item.style.alignItems = "center";
    item.style.justifyContent = "space-between";
    item.innerHTML = `
      <div style="display:flex; align-items:center; gap:6px;">
        <div style="width:8px; height:8px; background:${s.color}; border-radius:2px;"></div>
        <span style="color:var(--text-primary); font-family:var(--font-mono);">${s.category}</span>
      </div>
      <span style="font-family:var(--font-mono); color:var(--text-secondary); font-weight:600;">${s.count} (${s.percentage}%)</span>
    `;
    list.appendChild(item);
  });
}

/* ── 5. Queue Evolution Time-Series ────────────────────────────────────────── */
function renderQueueEvolution(queueData) {
  const canvas = document.getElementById("queueEvolutionCanvas");
  const meta = document.getElementById("queueMetaStats");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width || 300;
  canvas.height = rect.height || 130;

  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const points = (queueData && queueData.points) ? queueData.points : [];
  const maxQ = (queueData && queueData.max_queue_m) ? queueData.max_queue_m : 0;
  if (meta) meta.textContent = `MAX: ${maxQ.toFixed(1)}m`;

  if (points.length === 0) {
    ctx.fillStyle = "#64748B";
    ctx.font = "10px monospace";
    ctx.textAlign = "center";
    ctx.fillText("No queue observations recorded", w / 2, h / 2);
    return;
  }

  const padLeft = 36;
  const padBottom = 20;
  const padTop = 14;
  const padRight = 14;
  const plotW = w - padLeft - padRight;
  const plotH = h - padTop - padBottom;
  const maxVal = Math.max(20.0, maxQ * 1.25);

  // Background Grid
  ctx.strokeStyle = "rgba(244, 63, 94, 0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 2; i++) {
    const yVal = maxVal * (i / 2);
    const py = padTop + plotH - (plotH * (i / 2));
    ctx.beginPath();
    ctx.moveTo(padLeft, py);
    ctx.lineTo(padLeft + plotW, py);
    ctx.stroke();

    ctx.fillStyle = "#64748B";
    ctx.font = "9px monospace";
    ctx.textAlign = "right";
    ctx.fillText(`${Math.round(yVal)}m`, padLeft - 4, py + 3);
  }

  const stepX = points.length > 1 ? plotW / (points.length - 1) : plotW;

  // Queue Area Fill
  ctx.beginPath();
  points.forEach((p, i) => {
    const px = padLeft + i * stepX;
    const py = padTop + plotH - (plotH * (p.queue_meters / maxVal));
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.lineTo(padLeft + (points.length - 1) * stepX, padTop + plotH);
  ctx.lineTo(padLeft, padTop + plotH);
  ctx.closePath();

  const qGrad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
  qGrad.addColorStop(0, "rgba(244, 63, 94, 0.4)");
  qGrad.addColorStop(1, "rgba(244, 63, 94, 0.02)");
  ctx.fillStyle = qGrad;
  ctx.fill();

  // Queue Line
  ctx.beginPath();
  points.forEach((p, i) => {
    const px = padLeft + i * stepX;
    const py = padTop + plotH - (plotH * (p.queue_meters / maxVal));
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.strokeStyle = "#F43F5E";
  ctx.lineWidth = 2;
  ctx.stroke();
}

/* ── 6. Origin–Destination Matrix ──────────────────────────────────────────── */
function renderOdMatrix(odData) {
  const table = document.getElementById("odMatrixTable");
  if (!table) return;
  table.innerHTML = "";

  if (!odData || odData.length === 0) {
    table.innerHTML = '<tr><td style="color:var(--text-muted);">No OD movements recorded</td></tr>';
    return;
  }

  const cardinals = ["N", "S", "E", "W"];

  // Table Header
  let thead = "<tr><th>O \\ D</th>";
  cardinals.forEach(c => {
    thead += `<th>${c}</th>`;
  });
  thead += "</tr>";
  table.innerHTML = thead;

  // Find max count for dynamic cell coloring
  let maxCount = 1;
  odData.forEach(row => {
    cardinals.forEach(dest => {
      const cell = row.destinations[dest];
      if (cell && cell.count > maxCount) maxCount = cell.count;
    });
  });

  // Table Rows
  odData.forEach(row => {
    const tr = document.createElement("tr");
    let rowHtml = `<th style="background:rgba(19,31,55,0.8);">${row.origin}</th>`;

    cardinals.forEach(dest => {
      const cell = row.destinations[dest];
      const count = cell ? cell.count : 0;
      const isDiag = (row.origin === dest);
      const isSelected = (l3OriginFilter === row.origin && l3DestFilter === dest);

      const alpha = isDiag ? 0.05 : Math.max(0.1, (count / maxCount) * 0.7);
      const bgStyle = isDiag ? "background:rgba(255,255,255,0.02); color:#64748B;" : `background:rgba(56,189,248,${alpha}); color:var(--text-primary); font-weight:bold;`;
      const cellClass = `od-cell ${isSelected ? 'active' : ''}`;

      rowHtml += `<td class="${cellClass}" data-orig="${row.origin}" data-dest="${dest}" style="${bgStyle}">${isDiag ? '—' : count}</td>`;
    });

    tr.innerHTML = rowHtml;
    table.appendChild(tr);
  });

  // Add click handler to OD cells
  table.querySelectorAll(".od-cell").forEach(cell => {
    cell.onclick = () => {
      const orig = cell.getAttribute("data-orig");
      const dest = cell.getAttribute("data-dest");
      if (orig === dest) return;

      if (l3OriginFilter === orig && l3DestFilter === dest) {
        clearL3Filter();
      } else {
        applyL3Filter("od", { origin: orig, dest: dest }, `OD CORRIDOR: ${orig} → ${dest}`);
      }
    };
  });
}

/* ── 7. Flow-Density Fundamental Relationship ──────────────────────────────── */
function renderFlowDensityScatter(fdData) {
  const canvas = document.getElementById("flowDensityCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width || 300;
  canvas.height = rect.height || 130;

  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const points = (fdData && fdData.points) ? fdData.points : [];
  if (points.length === 0) {
    ctx.fillStyle = "#64748B";
    ctx.font = "10px monospace";
    ctx.textAlign = "center";
    ctx.fillText("No flow-density observations recorded", w / 2, h / 2);
    return;
  }

  const padLeft = 36;
  const padBottom = 20;
  const padTop = 14;
  const padRight = 14;
  const plotW = w - padLeft - padRight;
  const plotH = h - padTop - padBottom;

  const maxDens = 100.0;
  const maxFlow = Math.max(50.0, ...points.map(p => p.flow_vpm * 1.2));

  // Background Regime Zones
  // Free Flow Zone (0 to 35 veh/km)
  const freeFlowW = plotW * (35.0 / maxDens);
  ctx.fillStyle = "rgba(200, 242, 58, 0.06)";
  ctx.fillRect(padLeft, padTop, freeFlowW, plotH);

  // High Flow Zone (35 to 70 veh/km)
  const highFlowW = plotW * (35.0 / maxDens);
  ctx.fillStyle = "rgba(56, 189, 248, 0.06)";
  ctx.fillRect(padLeft + freeFlowW, padTop, highFlowW, plotH);

  // Congested Zone (70 to 100 veh/km)
  const congW = plotW - (freeFlowW + highFlowW);
  ctx.fillStyle = "rgba(244, 63, 94, 0.06)";
  ctx.fillRect(padLeft + freeFlowW + highFlowW, padTop, congW, plotH);

  // Axis lines
  ctx.strokeStyle = "rgba(56, 189, 248, 0.2)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padLeft, padTop);
  ctx.lineTo(padLeft, padTop + plotH);
  ctx.lineTo(padLeft + plotW, padTop + plotH);
  ctx.stroke();

  // Plot Scatter Points
  points.forEach(p => {
    const px = padLeft + Math.min(plotW, plotW * (p.density_vpk / maxDens));
    const py = padTop + plotH - Math.min(plotH, plotH * (p.flow_vpm / maxFlow));

    let dotColor = "#C8F23A"; // Free Flow
    if (p.regime === "HIGH_FLOW") dotColor = "#38BDF8";
    else if (p.regime === "CONGESTED") dotColor = "#F43F5E";

    ctx.fillStyle = dotColor;
    ctx.shadowColor = dotColor;
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.arc(px, py, 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  });

  // Labels
  ctx.fillStyle = "#64748B";
  ctx.font = "8.5px monospace";
  ctx.textAlign = "center";
  ctx.fillText("DENSITY (veh/km)", padLeft + plotW / 2, padTop + plotH + 16);
}

