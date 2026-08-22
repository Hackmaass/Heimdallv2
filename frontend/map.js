/**
 * Heimdallv2 2D Top-Down Trajectory Visualizer & Multi-Layer Analytics Engine
 * Layers:
 * 1. Video Background Overlay (Align trajectories over aerial footage)
 * 2. Trajectory Movement Trails (Fine-grained & Taxonomy color-coded)
 * 3. Traffic Density Heatmap (Dwell & Congestion zones)
 * 4. Speed Kinematics Layer (Color-coded by metric speed / relative speed)
 * 5. Conflict & Hazard Hotspots (Crossing trajectories & close proximity)
 * 6. Directional Velocity Arrows & Fine-Grained Class Badges
 * 7. Ground-Plane Calibration Reference Quadrangle
 */

class TrajectoryMapVisualizer {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext("2d");

    this.tracks = new Map(); // trackId -> track object with trail history
    this.selectedTrackId = null;
    this.classFilters = new Set(); // Empty means show all

    // Analytical Layer Toggles
    this.layerVideoOverlay = true;
    this.videoOpacity = 0.55;
    this.layerTrails = true;
    this.layerHeatmap = false;
    this.layerSpeed = false;
    this.layerConflicts = false;
    this.layerArrows = true;
    this.showLabels = true;

    // Ground-Plane Calibration State
    this.isCalibrating = false;
    this.calibPoints = [];
    this.onCalibPointAdded = null;

    // Video Background Frame
    this.bgImage = null;
    this.bgWidth = 640;
    this.bgHeight = 480;

    // Viewport Transform (Pan & Zoom)
    this.scale = 1.0;
    this.panX = 0;
    this.panY = 0;
    this.isDragging = false;
    this.dragStartX = 0;
    this.dragStartY = 0;
    this.hasAutoFitted = false;

    // Taxonomy Palette
    this.colors = {
      PERSON: "#00FFB2",
      BICYCLE: "#00E5FF",
      MOTORCYCLE: "#C8F23A",
      CAR: "#38BDF8",
      LGV: "#FB923C",
      HGV: "#F43F5E",
      BUS: "#A855F7",
      OTHER_VEHICLE: "#E2E8F0"
    };

    // Fine-Grained Palette
    this.fineColors = {
      "Pedestrian": "#00FFB2",
      "Bicycle": "#00E5FF",
      "Motorcycle": "#C8F23A",
      "Scooter": "#A3E635",
      "Auto Rickshaw": "#FACC15",
      "Sedan": "#38BDF8",
      "Hatchback": "#60A5FA",
      "SUV": "#818CF8",
      "Car": "#38BDF8",
      "Van": "#FB923C",
      "Bus": "#A855F7",
      "Truck": "#F43F5E",
      "Heavy Truck": "#E11D48",
    };

    this._initEvents();
    this.resize();
    this.render();
  }

  _initEvents() {
    window.addEventListener("resize", () => {
      this.resize();
      this.autoFit();
    });

    this.canvas.addEventListener("mousedown", (e) => {
      this.isDragging = true;
      this.dragStartX = e.clientX - this.panX;
      this.dragStartY = e.clientY - this.panY;
    });

    window.addEventListener("mousemove", (e) => {
      if (!this.isDragging) return;
      this.panX = e.clientX - this.dragStartX;
      this.panY = e.clientY - this.dragStartY;
      this.render();
    });

    window.addEventListener("mouseup", () => {
      this.isDragging = false;
    });

    this.canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const rect = this.canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
      const newScale = Math.max(0.05, Math.min(10.0, this.scale * zoomFactor));

      // Zoom towards mouse pointer
      this.panX = mouseX - (mouseX - this.panX) * (newScale / this.scale);
      this.panY = mouseY - (mouseY - this.panY) * (newScale / this.scale);
      this.scale = newScale;
      this.render();
    });

    // Object Selection & Calibration Point Picking
    this.canvas.addEventListener("click", (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;

      const worldX = (clickX - this.panX) / this.scale;
      const worldY = (clickY - this.panY) / this.scale;

      if (this.isCalibrating) {
        if (this.calibPoints.length >= 4) {
          this.calibPoints = [];
        }
        this.calibPoints.push([Math.round(worldX), Math.round(worldY)]);
        if (this.onCalibPointAdded) {
          this.onCalibPointAdded(this.calibPoints);
        }
        this.render();
        return;
      }

      let closestId = null;
      let minDistance = 25 / this.scale; // click hit radius in world units

      for (const [id, track] of this.tracks.entries()) {
        if (this.classFilters.has(track.class)) continue;
        if (!track.centroid) continue;

        const dist = Math.hypot(track.centroid[0] - worldX, track.centroid[1] - worldY);
        if (dist < minDistance) {
          minDistance = dist;
          closestId = id;
        }
      }

      this.selectedTrackId = closestId;
      if (window.onTrackSelected) {
        window.onTrackSelected(closestId ? this.tracks.get(closestId) : null);
      }
      this.render();
    });
  }

  resize() {
    const parent = this.canvas.parentElement;
    if (parent) {
      this.canvas.width = parent.clientWidth;
      this.canvas.height = parent.clientHeight;
      this.render();
    }
  }

  setVideoBackground(imageElement) {
    if (!imageElement || !imageElement.naturalWidth) return;
    this.bgImage = imageElement;
    this.bgWidth = imageElement.naturalWidth || 1920;
    this.bgHeight = imageElement.naturalHeight || 1080;

    if (!this.hasAutoFitted) {
      this.autoFit();
      this.hasAutoFitted = true;
    }
    this.render();
  }

  autoFit() {
    if (!this.canvas.width || !this.canvas.height) return;

    let minX = 0, minY = 0, maxX = this.bgWidth, maxY = this.bgHeight;

    if (this.tracks.size > 0) {
      for (const t of this.tracks.values()) {
        if (t.centroid) {
          minX = Math.min(minX, t.centroid[0]);
          minY = Math.min(minY, t.centroid[1]);
          maxX = Math.max(maxX, t.centroid[0]);
          maxY = Math.max(maxY, t.centroid[1]);
        }
      }
    }

    const padding = 40;
    const contentW = Math.max(200, maxX - minX);
    const contentH = Math.max(200, maxY - minY);

    const scaleX = (this.canvas.width - padding * 2) / contentW;
    const scaleY = (this.canvas.height - padding * 2) / contentH;

    this.scale = Math.max(0.1, Math.min(scaleX, scaleY, 2.0));
    this.panX = (this.canvas.width - contentW * this.scale) / 2 - minX * this.scale;
    this.panY = (this.canvas.height - contentH * this.scale) / 2 - minY * this.scale;

    this.render();
  }

  resetView() {
    this.scale = 1.0;
    this.panX = 0;
    this.panY = 0;
    this.autoFit();
  }

  updateLiveTracks(trackList) {
    if (!Array.isArray(trackList)) return;

    for (const t of trackList) {
      const id = t.id;
      if (!this.tracks.has(id)) {
        this.tracks.set(id, {
          id: id,
          class: t.class || "CAR",
          fine_grained_class: t.fine_grained_class || "Car",
          fine_grained_conf: t.fine_grained_conf || 0.90,
          confidence: t.confidence || 0.9,
          centroid: t.centroid,
          bbox: t.bbox,
          speed: t.speed || 0,
          velocity_kmh: t.velocity_kmh,
          velocity_mps: t.velocity_mps,
          acceleration_mps2: t.acceleration_mps2,
          world_pos: t.world_pos,
          quality_flag: t.quality_flag || "VALID_HIGH_CONFIDENCE",
          is_calibrated: t.is_calibrated || false,
          speed_unit: t.speed_unit || "px/s",
          heading: t.heading || 0,
          duration: t.duration || 0,
          distance_travelled_m: t.distance_travelled_m || 0,
          trail: t.trail || [t.centroid],
          lastUpdate: Date.now()
        });
      } else {
        const existing = this.tracks.get(id);
        existing.centroid = t.centroid;
        existing.bbox = t.bbox;
        existing.speed = t.speed !== undefined ? t.speed : existing.speed;
        existing.velocity_kmh = t.velocity_kmh;
        existing.velocity_mps = t.velocity_mps;
        existing.acceleration_mps2 = t.acceleration_mps2;
        existing.world_pos = t.world_pos;
        existing.quality_flag = t.quality_flag || existing.quality_flag;
        existing.is_calibrated = t.is_calibrated || existing.is_calibrated;
        existing.speed_unit = t.speed_unit || existing.speed_unit;
        existing.heading = t.heading !== undefined ? t.heading : existing.heading;
        existing.duration = t.duration || existing.duration;
        existing.distance_travelled_m = t.distance_travelled_m || existing.distance_travelled_m;
        existing.fine_grained_class = t.fine_grained_class || existing.fine_grained_class;
        existing.fine_grained_conf = t.fine_grained_conf || existing.fine_grained_conf;
        existing.lastUpdate = Date.now();

        if (t.trail && t.trail.length > 0) {
          existing.trail = t.trail;
        } else if (t.centroid) {
          existing.trail.push(t.centroid);
          if (existing.trail.length > 150) existing.trail.shift();
        }
      }
    }

    if (!this.hasAutoFitted && this.tracks.size > 0) {
      this.autoFit();
      this.hasAutoFitted = true;
    }

    this.render();
  }

  loadPersistedTrajectories(trajectories) {
    if (!Array.isArray(trajectories)) return;
    this.tracks.clear();
    for (const t of trajectories) {
      this.tracks.set(t.id, {
        id: t.id,
        class: t.class || "CAR",
        fine_grained_class: t.fine_grained_class || "Car",
        confidence: t.confidence || 0.9,
        centroid: t.centroid,
        bbox: t.bbox,
        speed: t.speed || 0,
        velocity_kmh: t.velocity_kmh,
        velocity_mps: t.velocity_mps,
        acceleration_mps2: t.accel_mps2 || t.acceleration_mps2,
        world_pos: (t.world_x !== undefined && t.world_y !== undefined) ? [t.world_x, t.world_y] : null,
        quality_flag: t.quality_flag || "VALID_HIGH_CONFIDENCE",
        heading: t.heading || 0,
        duration: t.duration || 0,
        distance_travelled_m: t.total_distance_m || 0,
        trail: t.trail || (t.centroid ? [t.centroid] : []),
        lastUpdate: Date.now()
      });
    }
    this.autoFit();
    this.render();
  }

  clear() {
    this.tracks.clear();
    this.selectedTrackId = null;
    this.calibPoints = [];
    this.render();
  }

  _getSpeedColor(speed) {
    if (speed < 10) return "#00E5FF";      // Cyan (Slow)
    if (speed < 25) return "#00FFB2";      // Green
    if (speed < 45) return "#C8F23A";      // Yellow-Green
    if (speed < 70) return "#FB923C";      // Orange
    return "#F43F5E";                      // Red (High Speed)
  }

  render() {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;

    ctx.clearRect(0, 0, w, h);

    // Background Canvas Styling
    ctx.fillStyle = "#090D16";
    ctx.fillRect(0, 0, w, h);

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.scale, this.scale);

    // ── LAYER 1: Tactical Grid ───────────────────────────────────────────────
    ctx.strokeStyle = "rgba(255, 255, 255, 0.035)";
    ctx.lineWidth = 1 / this.scale;
    const gridSize = 100;
    const startX = Math.floor(-this.panX / this.scale / gridSize) * gridSize;
    const endX = startX + (w / this.scale) + gridSize * 2;
    const startY = Math.floor(-this.panY / this.scale / gridSize) * gridSize;
    const endY = startY + (h / this.scale) + gridSize * 2;

    ctx.beginPath();
    for (let x = startX; x < endX; x += gridSize) {
      ctx.moveTo(x, startY);
      ctx.lineTo(x, endY);
    }
    for (let y = startY; y < endY; y += gridSize) {
      ctx.moveTo(startX, y);
      ctx.lineTo(endX, y);
    }
    ctx.stroke();

    // ── LAYER 2: Video Overlay ───────────────────────────────────────────────
    if (this.layerVideoOverlay && this.bgImage) {
      ctx.save();
      ctx.globalAlpha = this.videoOpacity;
      try {
        ctx.drawImage(this.bgImage, 0, 0, this.bgWidth, this.bgHeight);
      } catch (e) {}
      ctx.restore();

      ctx.strokeStyle = "rgba(56, 189, 248, 0.35)";
      ctx.lineWidth = 1.5 / this.scale;
      ctx.strokeRect(0, 0, this.bgWidth, this.bgHeight);
    }

    // ── LAYER 3: Density Heatmap ─────────────────────────────────────────────
    if (this.layerHeatmap) {
      ctx.save();
      ctx.globalCompositeOperation = "screen";
      for (const [id, t] of this.tracks.entries()) {
        if (this.classFilters.has(t.class)) continue;
        const pts = t.trail || [t.centroid];
        for (let i = 0; i < pts.length; i += 2) {
          const [px, py] = pts[i];
          const grad = ctx.createRadialGradient(px, py, 2 / this.scale, px, py, 24 / this.scale);
          grad.addColorStop(0, "rgba(255, 60, 0, 0.55)");
          grad.addColorStop(0.4, "rgba(255, 180, 0, 0.35)");
          grad.addColorStop(0.8, "rgba(0, 229, 255, 0.15)");
          grad.addColorStop(1, "rgba(0, 0, 0, 0)");
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(px, py, 24 / this.scale, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.restore();
    }

    // ── LAYER 4: Trajectory Trails (Segment-Gated) ───────────────────────────
    if (this.layerTrails) {
      for (const [id, t] of this.tracks.entries()) {
        if (this.classFilters.has(t.class)) continue;
        if (!t.trail || t.trail.length < 2) continue;

        const isSelected = (id === this.selectedTrackId);
        const fineCls = t.fine_grained_class || "Car";
        const baseColor = this.layerSpeed ? this._getSpeedColor(t.speed) : (this.fineColors[fineCls] || this.colors[t.class] || "#38BDF8");

        ctx.strokeStyle = isSelected ? "#FFFFFF" : baseColor;
        ctx.lineWidth = isSelected ? 3.5 / this.scale : (this.layerSpeed ? 2.5 / this.scale : 2.0 / this.scale);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";

        // Segment splitting: breaks trails if consecutive points exceed 60px (prevents cross-building jumps)
        const pts = t.trail;
        const segments = [];
        let currSeg = [pts[0]];
        for (let i = 1; i < pts.length; i++) {
          const dist = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
          if (dist > 60.0) {
            if (currSeg.length >= 2) segments.push(currSeg);
            currSeg = [pts[i]];
          } else {
            currSeg.push(pts[i]);
          }
        }
        if (currSeg.length >= 2) segments.push(currSeg);

        // Draw Smooth Spline Curves per segment
        for (const seg of segments) {
          ctx.beginPath();
          ctx.moveTo(seg[0][0], seg[0][1]);
          if (seg.length === 2) {
            ctx.lineTo(seg[1][0], seg[1][1]);
          } else {
            for (let i = 1; i < seg.length - 1; i++) {
              const xc = (seg[i][0] + seg[i + 1][0]) / 2;
              const yc = (seg[i][1] + seg[i + 1][1]) / 2;
              ctx.quadraticCurveTo(seg[i][0], seg[i][1], xc, yc);
            }
            ctx.lineTo(seg[seg.length - 1][0], seg[seg.length - 1][1]);
          }
          ctx.stroke();
        }

        // Trail point markers
        for (let i = 0; i < t.trail.length; i += 4) {
          const pt = t.trail[i];
          ctx.fillStyle = isSelected ? "#FFFFFF" : baseColor;
          ctx.beginPath();
          ctx.arc(pt[0], pt[1], (isSelected ? 2.5 : 1.5) / this.scale, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // ── LAYER 5: Conflict & Hazard Hotspots ──────────────────────────────────
    if (this.layerConflicts) {
      const conflictPoints = [];
      const trackArr = Array.from(this.tracks.values()).filter(t => !this.classFilters.has(t.class));

      for (let i = 0; i < trackArr.length; i++) {
        for (let j = i + 1; j < trackArr.length; j++) {
          const t1 = trackArr[i];
          const t2 = trackArr[j];
          if (!t1.centroid || !t2.centroid) continue;

          const dist = Math.hypot(t1.centroid[0] - t2.centroid[0], t1.centroid[1] - t2.centroid[1]);
          if (dist < 45.0) {
            conflictPoints.push({
              x: (t1.centroid[0] + t2.centroid[0]) / 2,
              y: (t1.centroid[1] + t2.centroid[1]) / 2,
              t1: t1.id,
              t2: t2.id,
              dist: Math.round(dist)
            });
          }
        }
      }

      for (const cp of conflictPoints) {
        ctx.strokeStyle = "#F43F5E";
        ctx.lineWidth = 2 / this.scale;
        ctx.beginPath();
        ctx.arc(cp.x, cp.y, 16 / this.scale, 0, Math.PI * 2);
        ctx.stroke();

        ctx.fillStyle = "rgba(244, 63, 94, 0.25)";
        ctx.fill();

        ctx.fillStyle = "#FFFFFF";
        ctx.font = `bold ${Math.max(9, Math.round(10 / this.scale))}px monospace`;
        ctx.fillText(`⚠️ CONFLICT #${cp.t1}-#${cp.t2}`, cp.x + 14 / this.scale, cp.y);
      }
    }

    // ── LAYER 6: Ground-Plane Calibration Quadrangle Overlay ──────────────────
    if (this.calibPoints && this.calibPoints.length > 0) {
      ctx.strokeStyle = "#00E5FF";
      ctx.lineWidth = 2.5 / this.scale;
      ctx.setLineDash([6 / this.scale, 4 / this.scale]);

      ctx.beginPath();
      ctx.moveTo(this.calibPoints[0][0], this.calibPoints[0][1]);
      for (let i = 1; i < this.calibPoints.length; i++) {
        ctx.lineTo(this.calibPoints[i][0], this.calibPoints[i][1]);
      }
      if (this.calibPoints.length === 4) {
        ctx.closePath();
      }
      ctx.stroke();
      ctx.setLineDash([]);

      if (this.calibPoints.length === 4) {
        ctx.fillStyle = "rgba(0, 229, 255, 0.12)";
        ctx.fill();
      }

      // Point Badges (P0, P1, P2, P3)
      for (let i = 0; i < this.calibPoints.length; i++) {
        const [px, py] = this.calibPoints[i];
        ctx.fillStyle = "#00E5FF";
        ctx.beginPath();
        ctx.arc(px, py, 6 / this.scale, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#090D16";
        ctx.font = `bold ${Math.max(9, Math.round(10 / this.scale))}px monospace`;
        ctx.fillText(`P${i}`, px - 3 / this.scale, py + 3.5 / this.scale);
      }
    }

    // ── LAYER 7: Centroid Points, Direction Vectors & Fine-Grained Badges ────
    for (const [id, t] of this.tracks.entries()) {
      if (this.classFilters.has(t.class)) continue;
      if (!t.centroid) continue;

      const [cx, cy] = t.centroid;
      const isSelected = (id === this.selectedTrackId);
      const fineCls = t.fine_grained_class || "Car";
      const color = this.layerSpeed ? this._getSpeedColor(t.speed) : (this.fineColors[fineCls] || this.colors[t.class] || "#38BDF8");

      // Centroid Circle
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(cx, cy, (isSelected ? 7 : 4.5) / this.scale, 0, Math.PI * 2);
      ctx.fill();

      if (isSelected) {
        ctx.strokeStyle = "#FFFFFF";
        ctx.lineWidth = 2 / this.scale;
        ctx.beginPath();
        ctx.arc(cx, cy, 11 / this.scale, 0, Math.PI * 2);
        ctx.stroke();
      }

      // Directional Vector Arrow
      if (this.layerArrows && t.heading !== undefined) {
        const rad = (t.heading * Math.PI) / 180.0;
        const arrowLen = Math.max(14, Math.min(32, t.speed * 0.45)) / this.scale;
        const endX = cx + Math.cos(rad) * arrowLen;
        const endY = cy + Math.sin(rad) * arrowLen;

        ctx.strokeStyle = color;
        ctx.lineWidth = (isSelected ? 2.5 : 1.5) / this.scale;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(endX, endY);
        ctx.stroke();

        const headLen = 5 / this.scale;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(endX, endY);
        ctx.lineTo(endX - headLen * Math.cos(rad - Math.PI / 6), endY - headLen * Math.sin(rad - Math.PI / 6));
        ctx.lineTo(endX - headLen * Math.cos(rad + Math.PI / 6), endY - headLen * Math.sin(rad + Math.PI / 6));
        ctx.closePath();
        ctx.fill();
      }

      // Tactical Badge: #ID Fine-Class & Speed (km/h)
      if (this.showLabels || isSelected) {
        const speedText = t.velocity_kmh !== undefined && t.velocity_kmh !== null ? `${t.velocity_kmh} km/h` : `${t.speed} ${t.speed_unit || 'px/s'}`;
        const label = `#${id} ${fineCls} | ${speedText}`;
        const fontSize = Math.max(8.5, Math.round((isSelected ? 11 : 9.5) / this.scale));
        ctx.font = `${isSelected ? 'bold ' : ''}${fontSize}px "JetBrains Mono", monospace`;

        const tw = ctx.measureText(label).width;
        const th = fontSize + 4 / this.scale;

        ctx.fillStyle = isSelected ? "rgba(255, 255, 255, 0.95)" : "rgba(9, 13, 22, 0.85)";
        ctx.fillRect(cx + 8 / this.scale, cy - th / 2, tw + 6 / this.scale, th);

        ctx.strokeStyle = color;
        ctx.lineWidth = 1 / this.scale;
        ctx.strokeRect(cx + 8 / this.scale, cy - th / 2, tw + 6 / this.scale, th);

        ctx.fillStyle = isSelected ? "#090D16" : color;
        ctx.fillText(label, cx + 11 / this.scale, cy + th * 0.28);
      }
    }

    ctx.restore();
  }
}

window.TrajectoryMapVisualizer = TrajectoryMapVisualizer;
