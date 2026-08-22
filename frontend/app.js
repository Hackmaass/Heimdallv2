/**
 * Heimdallv2 Tactical Command Center Application Logic
 * Level 1 Core Baseline + Level 2 Extended Object-Level Insights & Calibration
 */

let visualizer = null;
let ws = null;
let currentJobId = null;
let pollingInterval = null;

// Initialize when DOM loads
document.addEventListener("DOMContentLoaded", () => {
  visualizer = new TrajectoryMapVisualizer("trajectoryCanvas");

  window.onTrackSelected = (track) => {
    updateInspector(track);
  };

  visualizer.onCalibPointAdded = (pts) => {
    updateCalibPointsDisplay(pts);
  };

  connectWebSocket();
  initEventListeners();
  loadInitialTelemetry();
  loadCalibrationStatus();
  loadSessionTrajectories();
});

// ── Real-Time WebSocket Telemetry & Video Frame Receiver ──────────────────────

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/tracking`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    const el = document.getElementById("sysWsStatus");
    if (el) {
      el.textContent = "ONLINE (LIVE)";
      el.style.color = "var(--accent-lime)";
    }
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
    const el = document.getElementById("sysWsStatus");
    if (el) {
      el.textContent = "DISCONNECTED";
      el.style.color = "var(--accent-rose)";
    }
    setTimeout(connectWebSocket, 2500);
  };
}

function handleLiveFrame(data) {
  // Update Live Video Frame
  if (data.image_b64) {
    const imgEl = document.getElementById("liveVideoCanvas");
    imgEl.src = `data:image/jpeg;base64,${data.image_b64}`;
    if (visualizer.layerVideoOverlay) {
      visualizer.setVideoBackground(imgEl);
    }
  }

  // Update Frame HUD
  if (data.frame !== undefined) {
    document.getElementById("hudFrameIdx").textContent = `FRAME: ${data.frame}`;
    document.getElementById("hudTimestamp").textContent = `T: ${data.timestamp}s`;
  }

  // Update Telemetry
  if (data.telemetry) {
    updateTelemetryHUD(data.telemetry);
  }

  // Update Trajectory Canvas & Active Tracks
  if (data.tracks) {
    visualizer.updateLiveTracks(data.tracks);
    updateTrackState(data.tracks, data.total_unique);

    // If an object is currently selected, update its inspector values live
    if (visualizer.selectedTrackId) {
      const currentTrack = visualizer.tracks.get(visualizer.selectedTrackId);
      if (currentTrack) updateInspector(currentTrack);
    }
  }
}

function updateTelemetryHUD(t) {
  document.getElementById("telGps").textContent = `${t.lat.toFixed(4)}, ${t.lng.toFixed(4)}`;
  document.getElementById("telAlt").textContent = `${t.alt.toFixed(1)} m`;
  document.getElementById("telHeading").textContent = `${t.heading.toFixed(0)}°`;
  document.getElementById("telSpeed").textContent = `${t.speed.toFixed(1)} m/s`;
  document.getElementById("telBattery").textContent = `${t.battery.toFixed(0)}%`;
  document.getElementById("telMode").textContent = t.mode || "SURVEILLANCE";
}

function updateTrackState(tracks, totalUnique) {
  document.getElementById("sysActiveTracks").textContent = tracks.length;
  document.getElementById("sysTotalTracks").textContent = totalUnique || visualizer.tracks.size || tracks.length;

  // Level 2 Fine-Grained Breakdown Counts
  let cars = 0, rickshaws = 0, bikes = 0, buses = 0, hgv = 0, lgv = 0, ped = 0;

  for (const t of tracks) {
    const fc = (t.fine_grained_class || t.class || "").toLowerCase();
    if (fc.includes("rickshaw") || fc.includes("tricycle")) rickshaws++;
    else if (fc.includes("motor") || fc.includes("scooter") || fc.includes("bike")) bikes++;
    else if (fc.includes("bus")) buses++;
    else if (fc.includes("heavy") || fc.includes("truck")) hgv++;
    else if (fc.includes("van") || fc.includes("lgv")) lgv++;
    else if (fc.includes("pedestrian") || fc.includes("person")) ped++;
    else cars++;
  }

  document.getElementById("countCars").textContent = cars;
  document.getElementById("countRickshaws").textContent = rickshaws;
  document.getElementById("countBikes").textContent = bikes;
  document.getElementById("countBuses").textContent = buses;
  document.getElementById("countHgv").textContent = hgv;
  document.getElementById("countLgv").textContent = lgv;
  document.getElementById("countPedestrians").textContent = ped;

  // Render Table Rows with Level 2 Kinematic Metrics
  const tbody = document.getElementById("tracksTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";

  for (const t of tracks) {
    const tr = document.createElement("tr");
    if (visualizer.selectedTrackId === t.id) tr.classList.add("selected");

    tr.onclick = () => {
      visualizer.selectedTrackId = t.id;
      visualizer.render();
      updateInspector(t);
    };

    const fineCls = t.fine_grained_class || t.class || "Car";
    const speedStr = t.velocity_kmh !== undefined && t.velocity_kmh !== null ? `${t.velocity_kmh} km/h` : `${t.speed || 0} ${t.speed_unit || 'px/s'}`;
    const accelStr = t.acceleration_mps2 !== undefined && t.acceleration_mps2 !== null ? `${t.acceleration_mps2 > 0 ? '+' : ''}${t.acceleration_mps2} m/s²` : '--';
    const worldStr = t.world_pos ? `(${t.world_pos[0]}m, ${t.world_pos[1]}m)` : '--';
    const distStr = t.distance_travelled_m ? `${t.distance_travelled_m} m` : '--';
    const quality = t.quality_flag || "VALID";

    tr.innerHTML = `
      <td style="font-weight:700; color:#38BDF8;">#${t.id}</td>
      <td><span class="badge" style="background:rgba(56,189,248,0.15); color:#38BDF8;">${fineCls}</span></td>
      <td>${Math.round((t.confidence || 0.9) * 100)}%</td>
      <td style="font-weight:600; color:${t.velocity_kmh ? 'var(--accent-lime)' : 'var(--text-primary)'};">${speedStr}</td>
      <td>${accelStr}</td>
      <td style="font-size:10.5px; color:var(--text-secondary);">${worldStr}</td>
      <td>${(t.heading || 0).toFixed(0)}°</td>
      <td>${distStr}</td>
      <td><span class="badge ${quality === 'VALID_HIGH_CONFIDENCE' ? 'badge-lime' : 'badge-amber'}" style="font-size:9.5px;">${quality.replace('UNRELIABLE_', '')}</span></td>
    `;
    tbody.appendChild(tr);
  }
}

function updateInspector(track) {
  const card = document.getElementById("inspectorCard");
  if (!card) return;

  if (!track) {
    card.style.display = "none";
    return;
  }

  card.style.display = "block";
  const fineCls = track.fine_grained_class || track.class || "Car";
  const speedStr = track.velocity_kmh !== undefined && track.velocity_kmh !== null ? `${track.velocity_kmh} km/h (${track.velocity_mps || '--'} m/s)` : `${track.speed || 0} ${track.speed_unit || 'px/s'}`;
  const accelStr = track.acceleration_mps2 !== undefined && track.acceleration_mps2 !== null ? `${track.acceleration_mps2 > 0 ? '+' : ''}${track.acceleration_mps2} m/s²` : '--';
  const worldStr = track.world_pos ? `X: ${track.world_pos[0]}m, Y: ${track.world_pos[1]}m` : 'UNAVAILABLE (Uncalibrated)';
  const distStr = track.distance_travelled_m ? `${track.distance_travelled_m} m` : `${track.total_distance_px || '--'} px`;
  const quality = track.quality_flag || "VALID_HIGH_CONFIDENCE";

  document.getElementById("inspId").textContent = `#${track.id}`;
  document.getElementById("inspFineClass").textContent = fineCls.toUpperCase();
  document.getElementById("inspSpeed").textContent = speedStr;
  document.getElementById("inspAccel").textContent = accelStr;
  document.getElementById("inspWorldPos").textContent = worldStr;
  document.getElementById("inspHeading").textContent = `${(track.heading || 0).toFixed(0)}°`;
  document.getElementById("inspDist").textContent = distStr;
  document.getElementById("inspQuality").textContent = quality.replace("UNRELIABLE_", "");
  document.getElementById("inspConf").textContent = `${Math.round((track.confidence || 0.9) * 100)}%`;
  document.getElementById("inspDuration").textContent = `${(track.duration || 0).toFixed(1)}s`;
}

// ── Ground-Plane Calibration Workflow ─────────────────────────────────────────

async function loadCalibrationStatus() {
  try {
    const res = await fetch("/api/calibration");
    const data = await res.json();
    const badge = document.getElementById("headerCalibStatus");

    if (data.is_calibrated) {
      badge.textContent = `CALIBRATED (RMS: ${data.rms_error_m}m)`;
      badge.style.color = "var(--accent-lime)";
      if (data.image_points && visualizer) {
        visualizer.calibPoints = data.image_points;
        updateCalibPointsDisplay(data.image_points);
      }
    } else {
      badge.textContent = "UNCALIBRATED (px/s)";
      badge.style.color = "var(--accent-amber)";
    }
  } catch (e) {
    console.warn("Calibration fetch error:", e);
  }
}

function updateCalibPointsDisplay(pts) {
  const container = document.getElementById("calibPointsList");
  if (!container) return;

  if (!pts || pts.length === 0) {
    container.innerHTML = "Click 4 corners on 2D map: P0 (Top-Left), P1 (Top-Right), P2 (Bottom-Right), P3 (Bottom-Left)";
    return;
  }

  let html = "";
  for (let i = 0; i < 4; i++) {
    if (i < pts.length) {
      html += `<span style="color:var(--accent-cyan)">P${i}: [${pts[i][0]}, ${pts[i][1]}]</span> &nbsp; `;
    } else {
      html += `<span style="color:var(--text-muted)">P${i}: (Pending click)</span> &nbsp; `;
    }
  }
  container.innerHTML = html;
}

// ── Event Handlers & Modal Interactions ───────────────────────────────────────

function initEventListeners() {
  // Calibration Modal Triggers
  document.getElementById("btnOpenCalib").onclick = () => {
    document.getElementById("calibModal").classList.add("open");
    loadCalibrationStatus();
  };

  document.getElementById("btnPickPointsCanvas").onclick = () => {
    visualizer.isCalibrating = true;
    visualizer.calibPoints = [];
    updateCalibPointsDisplay([]);
    document.getElementById("canvasHint").textContent = "🎯 CLICK 4 ROAD CORRIDOR POINTS ON CANVAS: P0 -> P1 -> P2 -> P3";
    document.getElementById("calibModal").classList.remove("open");
  };

  document.getElementById("btnSaveCalib").onclick = async () => {
    const pts = visualizer.calibPoints;
    if (!pts || pts.length < 4) {
      alert("Please select exactly 4 reference points on the canvas before saving calibration.");
      return;
    }

    const widthM = parseFloat(document.getElementById("calibWidthM").value) || 7.5;
    const lengthM = parseFloat(document.getElementById("calibLengthM").value) || 25.0;

    try {
      const res = await fetch("/api/calibration", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_points: pts.slice(0, 4),
          road_width_m: widthM,
          road_length_m: lengthM,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Calibration failed.");

      visualizer.isCalibrating = false;
      document.getElementById("calibModal").classList.remove("open");
      loadCalibrationStatus();
      loadSessionTrajectories();
      alert(`Ground plane calibrated successfully! RMS Error: ${data.rms_error_m} meters.`);
    } catch (err) {
      alert("Calibration Error: " + err.message);
    }
  };

  document.getElementById("btnClearCalib").onclick = async () => {
    try {
      await fetch("/api/calibration", { method: "DELETE" });
      visualizer.calibPoints = [];
      updateCalibPointsDisplay([]);
      visualizer.isCalibrating = false;
      document.getElementById("calibModal").classList.remove("open");
      loadCalibrationStatus();
      loadSessionTrajectories();
    } catch (e) {
      console.error("Clear calib error:", e);
    }
  };

  // Export Buttons
  document.getElementById("btnExportCsv").onclick = () => {
    window.location.href = "/api/export/csv";
  };

  document.getElementById("btnExportJson").onclick = () => {
    window.location.href = "/api/export/json";
  };

  // Process Video Modal
  document.getElementById("btnOpenProcess").onclick = () => {
    document.getElementById("processModal").classList.add("open");
  };

  document.getElementById("btnStartProcessing").onclick = () => {
    startProcessingJob();
  };

  document.getElementById("btnResetView").onclick = async () => {
    visualizer.clear();
    try {
      await fetch("/api/trajectories", { method: "DELETE" });
    } catch (e) {}

    document.getElementById("countCars").textContent = "0";
    document.getElementById("countRickshaws").textContent = "0";
    document.getElementById("countBikes").textContent = "0";
    document.getElementById("countBuses").textContent = "0";
    document.getElementById("countHgv").textContent = "0";
    document.getElementById("countLgv").textContent = "0";
    document.getElementById("countPedestrians").textContent = "0";
    document.getElementById("tracksTableBody").innerHTML = "";
    document.getElementById("inspectorCard").style.display = "none";
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

  document.getElementById("selectOutputVideo").onchange = (e) => {
    const val = e.target.value;
    if (val) {
      videoEl.setAttribute("src", val);
      videoEl.load();
      videoEl.play().catch(() => {});
    }
  };

  document.getElementById("btnRefreshOutputs").onclick = () => {
    loadAvailableOutputVideos();
  };

  // Pin Current Frame to 2D Map Underlay
  document.getElementById("btnPinFrameToMap").onclick = () => {
    visualizer.setVideoBackground(liveImg);
    visualizer.layerVideoOverlay = true;
    document.getElementById("layerToggleVideo").classList.add("active");
    visualizer.autoFit();
  };

  // Analytical Layer Toggles
  const toggleLayer = (btnId, prop) => {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.onclick = () => {
      const active = btn.classList.toggle("active");
      visualizer[prop] = active;
      visualizer.render();
    };
  };

  toggleLayer("layerToggleVideo", "layerVideoOverlay");
  toggleLayer("layerToggleTrails", "layerTrails");
  toggleLayer("layerToggleHeatmap", "layerHeatmap");
  toggleLayer("layerToggleSpeed", "layerSpeed");
  toggleLayer("layerToggleConflicts", "layerConflicts");
  toggleLayer("layerToggleArrows", "layerArrows");

  const opacitySlider = document.getElementById("sliderVideoOpacity");
  if (opacitySlider) {
    opacitySlider.oninput = (e) => {
      visualizer.videoOpacity = parseFloat(e.target.value);
      visualizer.render();
    };
  }

  // Class Filter Badges
  document.querySelectorAll(".class-chip").forEach(chip => {
    chip.onclick = () => {
      const cls = chip.getAttribute("data-class");
      if (cls === "ALL") {
        document.querySelectorAll(".class-chip").forEach(c => c.classList.remove("active"));
        chip.classList.add("active");
        visualizer.classFilters.clear();
      } else {
        document.querySelector('.class-chip[data-class="ALL"]').classList.remove("active");
        const isActive = chip.classList.toggle("active");
        if (isActive) {
          visualizer.classFilters.delete(cls);
        } else {
          visualizer.classFilters.add(cls);
        }
      }
      visualizer.render();
    };
  });

  // SAHI Checkbox Toggle
  const sahiCheckbox = document.getElementById("checkEnableSAHI");
  const sahiOptions = document.getElementById("sahiOptions");
  if (sahiCheckbox && sahiOptions) {
    sahiCheckbox.onchange = () => {
      sahiOptions.style.display = sahiCheckbox.checked ? "block" : "none";
    };
  }

  // File Upload
  const dropzone = document.getElementById("dropzoneUpload");
  const fileInput = document.getElementById("inputVideoUpload");
  if (dropzone && fileInput) {
    dropzone.onclick = () => fileInput.click();
    fileInput.onchange = (e) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFileUpload(e.target.files[0]);
      }
    };
  }
}

async function handleFileUpload(file) {
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/video/upload", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");

    const select = document.getElementById("selectVideoFile");
    const opt = document.createElement("option");
    opt.value = data.saved_path;
    opt.textContent = `${data.original_filename} (${data.size_mb} MB)`;
    opt.selected = true;
    select.appendChild(opt);
    alert(`File uploaded successfully: ${data.original_filename}`);
  } catch (e) {
    alert("Upload error: " + e.message);
  }
}

async function startProcessingJob() {
  const videoPath = document.getElementById("selectVideoFile").value;
  const model = document.getElementById("selectModel").value;
  const tracker = document.getElementById("selectTracker").value;
  const conf = parseFloat(document.getElementById("selectConfidence").value) || 0.25;
  const durVal = document.getElementById("selectDuration").value;
  const durationSec = durVal === "all" ? null : parseFloat(durVal);
  const enableSahi = document.getElementById("checkEnableSAHI").checked;
  const sahiSlice = parseInt(document.getElementById("selectSAHISliceSize").value) || 960;

  const btn = document.getElementById("btnStartProcessing");
  btn.disabled = true;
  btn.textContent = "Launching Pipeline...";

  try {
    const res = await fetch("/api/video/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: videoPath,
        model_name: model,
        tracker_type: tracker,
        confidence_threshold: conf,
        duration_seconds: durationSec,
        enable_sahi: enableSahi,
        sahi_slice_size: sahiSlice,
      }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Launch failed");

    currentJobId = data.video_id;
    document.getElementById("modalFormContent").style.display = "none";
    document.getElementById("modalProgress").style.display = "block";
    document.getElementById("modalCompleteActions").style.display = "none";

    pollJobStatus(currentJobId);
  } catch (e) {
    alert("Pipeline Error: " + e.message);
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
        loadSessionTrajectories();

        const btn = document.getElementById("btnStartProcessing");
        btn.disabled = false;
        btn.textContent = "Launch Pipeline";

      } else if (data.status === "FAILED" || data.status === "ERROR") {
        clearInterval(pollingInterval);
        alert("Pipeline failed: " + data.error_message);
        document.getElementById("modalFormContent").style.display = "block";
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
      visualizer.loadPersistedTrajectories(data.trajectories);
      updateTrackState(data.trajectories, data.total);
    }
  } catch (e) {
    console.warn("Could not load trajectories:", e);
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
      const videoEl = document.getElementById("annotatedVideoPlayer");
      if (!videoEl.getAttribute("src") && data.outputs.length > 0) {
        select.selectedIndex = 1;
        videoEl.setAttribute("src", data.outputs[0].url);
        videoEl.load();
      }
    }
  } catch (e) {}
}

function loadInitialTelemetry() {
  fetch("/api/telemetry")
    .then(r => r.json())
    .then(t => updateTelemetryHUD(t))
    .catch(() => {});
}
