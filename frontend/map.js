/**
 * Heimdallv2 2D Top-Down Trajectory Visualizer & Multi-Layer Analytics Engine
 * Layers:
 * 1. Video Background Overlay (Align trajectories over aerial footage)
 * 2. Trajectory Movement Trails (Taxonomy color-coded)
 * 3. Traffic Density Heatmap (Dwell & Congestion zones)
 * 4. Speed Kinematics Layer (Color-coded by speed velocity)
 * 5. Conflict & Hazard Hotspots (Crossing trajectories & close proximity)
 * 6. Directional Velocity Arrows & Class Badges
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

    // Video Background Frame (for direct overlay)
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

    this.canvas.addEventListener("click", (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const clickX = (e.clientX - rect.left - this.panX) / this.scale;
      const clickY = (e.clientY - rect.top - this.panY) / this.scale;
      this._checkClickHit(clickX, clickY);
    });
  }

  resize() {
    if (!this.canvas) return;
    const parent = this.canvas.parentElement;
    if (parent && parent.clientWidth > 0 && parent.clientHeight > 0) {
      this.canvas.width = parent.clientWidth;
      this.canvas.height = parent.clientHeight;
      this.render();
    }
  }

  setBackgroundImage(imgElementOrSrc) {
    if (!imgElementOrSrc) return;
    if (typeof imgElementOrSrc === "string") {
      const img = new Image();
      img.onload = () => {
        this.bgImage = img;
        this.bgWidth = img.naturalWidth || 640;
        this.bgHeight = img.naturalHeight || 480;
        this.render();
      };
      img.src = imgElementOrSrc;
    } else if (imgElementOrSrc.tagName === "IMG" && imgElementOrSrc.complete && imgElementOrSrc.naturalWidth > 0) {
      this.bgImage = imgElementOrSrc;
      this.bgWidth = imgElementOrSrc.naturalWidth;
      this.bgHeight = imgElementOrSrc.naturalHeight;
      this.render();
    }
  }

  setVideoOpacity(opacity) {
    this.videoOpacity = Math.max(0.0, Math.min(1.0, opacity));
    this.render();
  }

  toggleLayer(layerName, enabled) {
    if (layerName === "video") this.layerVideoOverlay = enabled;
    else if (layerName === "trails") this.layerTrails = enabled;
    else if (layerName === "heatmap") this.layerHeatmap = enabled;
    else if (layerName === "speed") this.layerSpeed = enabled;
    else if (layerName === "conflicts") this.layerConflicts = enabled;
    else if (layerName === "arrows") this.layerArrows = enabled;
    else if (layerName === "labels") this.showLabels = enabled;
    this.render();
  }

  setClassFilter(className, isIncluded) {
    if (isIncluded) {
      this.classFilters.delete(className);
    } else {
      this.classFilters.add(className);
    }
    this.render();
  }

  clearClassFilters() {
    this.classFilters.clear();
    this.render();
  }

  updateTracks(trackList) {
    if (!trackList || trackList.length === 0) return;

    for (const t of trackList) {
      const rawTrail = t.trail && t.trail.length > 0 ? t.trail : [t.centroid];
      if (!this.tracks.has(t.id)) {
        this.tracks.set(t.id, {
          id: t.id,
          class: t.class,
          speed: t.speed || 0.0,
          heading: t.heading || 0.0,
          centroid: t.centroid,
          trail: [...rawTrail],
          lastSeen: Date.now()
        });
      } else {
        const existing = this.tracks.get(t.id);
        existing.speed = t.speed !== undefined ? t.speed : existing.speed;
        existing.heading = t.heading !== undefined ? t.heading : existing.heading;
        existing.centroid = t.centroid;
        existing.lastSeen = Date.now();

        if (t.trail && t.trail.length > 0) {
          existing.trail = t.trail;
        } else {
          existing.trail.push(t.centroid);
          if (existing.trail.length > 100) existing.trail.shift();
        }
      }
    }

    if (!this.hasAutoFitted && this.tracks.size > 0) {
      this.autoFit();
      this.hasAutoFitted = true;
    } else {
      this.render();
    }
  }

  loadFullTrajectories(trajectoryList) {
    this.tracks.clear();
    for (const t of trajectoryList) {
      const trail = t.trail && t.trail.length > 0 ? t.trail : [t.centroid];
      this.tracks.set(t.id, {
        id: t.id,
        class: t.class,
        speed: t.speed || 0.0,
        heading: t.heading || 0.0,
        centroid: t.centroid,
        trail: trail,
        lastSeen: Date.now()
      });
    }
    this.autoFit();
  }

  autoFit(padding = 48) {
    if (!this.canvas.width) return;

    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;

    if (this.tracks.size > 0) {
      for (const t of this.tracks.values()) {
        if (t.trail && t.trail.length > 0) {
          for (const pt of t.trail) {
            if (pt[0] < minX) minX = pt[0];
            if (pt[0] > maxX) maxX = pt[0];
            if (pt[1] < minY) minY = pt[1];
            if (pt[1] > maxY) maxY = pt[1];
          }
        } else if (t.centroid) {
          if (t.centroid[0] < minX) minX = t.centroid[0];
          if (t.centroid[0] > maxX) maxX = t.centroid[0];
          if (t.centroid[1] < minY) minY = t.centroid[1];
          if (t.centroid[1] > maxY) maxY = t.centroid[1];
        }
      }
    }

    // Fallback to background image dimensions if tracks are empty or small
    if (!isFinite(minX) || !isFinite(maxX) || (maxX - minX) < 10) {
      minX = 0;
      maxX = this.bgWidth || 640;
      minY = 0;
      maxY = this.bgHeight || 480;
    }

    const dataW = Math.max(80, maxX - minX);
    const dataH = Math.max(80, maxY - minY);

    const availableW = Math.max(100, this.canvas.width - padding * 2);
    const availableH = Math.max(100, this.canvas.height - padding * 2);

    const scaleX = availableW / dataW;
    const scaleY = availableH / dataH;
    this.scale = Math.min(scaleX, scaleY);

    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    this.panX = this.canvas.width / 2 - centerX * this.scale;
    this.panY = this.canvas.height / 2 - centerY * this.scale;

    this.render();
  }

  focusTrack(trackId) {
    const t = this.tracks.get(trackId);
    if (!t || !t.centroid) return;

    this.selectedTrackId = trackId;
    const [cx, cy] = t.centroid;

    this.scale = Math.max(1.2, this.scale);
    this.panX = this.canvas.width / 2 - cx * this.scale;
    this.panY = this.canvas.height / 2 - cy * this.scale;
    this.render();
  }

  setSelectedTrack(trackId) {
    this.selectedTrackId = trackId;
    this.focusTrack(trackId);
  }

  resetView() {
    this.hasAutoFitted = false;
    this.autoFit();
  }

  _checkClickHit(x, y) {
    let closestId = null;
    let minDist = 30.0 / this.scale;

    for (const [id, t] of this.tracks.entries()) {
      if (!t.centroid) continue;
      const dx = t.centroid[0] - x;
      const dy = t.centroid[1] - y;
      const dist = Math.hypot(dx, dy);
      if (dist < minDist) {
        minDist = dist;
        closestId = id;
      }
    }

    if (closestId !== null) {
      this.selectedTrackId = closestId;
      if (window.onTrackSelected) window.onTrackSelected(closestId);
    }
    this.render();
  }

  _getSpeedColor(speed) {
    if (speed < 4.0) return "#F43F5E"; // Crimson: Stopped / Congested
    if (speed < 15.0) return "#FB923C"; // Orange: Slow
    if (speed < 30.0) return "#00E5FF"; // Cyan: Moderate
    return "#C8F23A"; // Lime: Fast flow
  }

  render() {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;

    ctx.clearRect(0, 0, w, h);

    // Save context transform
    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.scale, this.scale);

    // ── LAYER 1: Aerial Video Background Underlay ────────────────────────────
    if (this.layerVideoOverlay && this.bgImage) {
      ctx.save();
      ctx.globalAlpha = this.videoOpacity;
      try {
        ctx.drawImage(this.bgImage, 0, 0, this.bgWidth, this.bgHeight);
        // Border around video frame
        ctx.strokeStyle = "rgba(0, 229, 255, 0.4)";
        ctx.lineWidth = 1.5 / this.scale;
        ctx.strokeRect(0, 0, this.bgWidth, this.bgHeight);
      } catch (e) {}
      ctx.restore();
    }

    // ── Coordinate Grid ──────────────────────────────────────────────────────
    ctx.strokeStyle = "rgba(56, 189, 248, 0.07)";
    ctx.lineWidth = 1 / this.scale;
    const gridSize = 64;
    const minX = -this.panX / this.scale - gridSize;
    const maxX = (w - this.panX) / this.scale + gridSize;
    const minY = -this.panY / this.scale - gridSize;
    const maxY = (h - this.panY) / this.scale + gridSize;

    for (let x = Math.floor(minX / gridSize) * gridSize; x <= maxX; x += gridSize) {
      ctx.beginPath();
      ctx.moveTo(x, minY);
      ctx.lineTo(x, maxY);
      ctx.stroke();
    }
    for (let y = Math.floor(minY / gridSize) * gridSize; y <= maxY; y += gridSize) {
      ctx.beginPath();
      ctx.moveTo(minX, y);
      ctx.lineTo(maxX, y);
      ctx.stroke();
    }

    // ── LAYER 2: Traffic Density Heatmap ─────────────────────────────────────
    if (this.layerHeatmap) {
      ctx.save();
      ctx.globalCompositeOperation = "screen";
      for (const t of this.tracks.values()) {
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

    // ── LAYER 3: Trajectory Trails (Taxonomy or Speed Mode) ───────────────────
    if (this.layerTrails) {
      for (const [id, t] of this.tracks.entries()) {
        if (this.classFilters.has(t.class)) continue;
        if (!t.trail || t.trail.length < 2) continue;

        const isSelected = (id === this.selectedTrackId);
        const baseColor = this.layerSpeed ? this._getSpeedColor(t.speed) : (this.colors[t.class] || "#38BDF8");

        ctx.strokeStyle = isSelected ? "#FFFFFF" : baseColor;
        ctx.lineWidth = isSelected ? 3.5 / this.scale : (this.layerSpeed ? 2.5 / this.scale : 2.0 / this.scale);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";

        ctx.beginPath();
        for (let i = 0; i < t.trail.length; i++) {
          const pt = t.trail[i];
          if (i === 0) ctx.moveTo(pt[0], pt[1]);
          else ctx.lineTo(pt[0], pt[1]);
        }
        ctx.stroke();

        // Trail point markers
        for (let i = 0; i < t.trail.length; i += 3) {
          const pt = t.trail[i];
          ctx.fillStyle = isSelected ? "#FFFFFF" : baseColor;
          ctx.beginPath();
          ctx.arc(pt[0], pt[1], (isSelected ? 2.5 : 1.6) / this.scale, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // ── LAYER 4: Conflict & Hazard Hotspots ──────────────────────────────────
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

    // ── LAYER 5: Centroid Points, Direction Vectors & Labels ──────────────────
    for (const [id, t] of this.tracks.entries()) {
      if (this.classFilters.has(t.class)) continue;
      if (!t.centroid) continue;

      const [cx, cy] = t.centroid;
      const isSelected = (id === this.selectedTrackId);
      const color = this.layerSpeed ? this._getSpeedColor(t.speed) : (this.colors[t.class] || "#38BDF8");

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

      // Velocity Direction Arrow
      if (this.layerArrows && t.speed > 1.0) {
        const rad = (t.heading * Math.PI) / 180.0;
        const arrowLen = (Math.min(32, Math.max(14, t.speed * 0.9))) / this.scale;
        const headX = cx + Math.cos(rad) * arrowLen;
        const headY = cy + Math.sin(rad) * arrowLen;

        ctx.strokeStyle = isSelected ? "#FFFFFF" : color;
        ctx.lineWidth = (isSelected ? 2.5 : 1.8) / this.scale;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(headX, headY);
        ctx.stroke();
      }

      // Text Badge
      if (this.showLabels || isSelected) {
        const fontSize = Math.max(10, Math.min(13, Math.round(11 / this.scale)));
        ctx.font = `bold ${fontSize}px monospace`;
        const speedText = this.layerSpeed ? ` ${t.speed.toFixed(0)}px/s` : "";
        const label = `#${t.id} ${t.class}${speedText}`;
        const textWidth = ctx.measureText(label).width;

        ctx.fillStyle = "rgba(15, 23, 42, 0.88)";
        ctx.fillRect(cx + 8 / this.scale, cy - 14 / this.scale, textWidth + 6 / this.scale, fontSize + 4 / this.scale);

        ctx.fillStyle = isSelected ? "#00E5FF" : (this.layerSpeed ? color : "#F8FAFC");
        ctx.fillText(label, cx + 11 / this.scale, cy - 2 / this.scale);
      }
    }

    ctx.restore();

    if (this.tracks.size === 0 && !this.bgImage) {
      ctx.fillStyle = "rgba(100, 116, 139, 0.7)";
      ctx.font = "12px monospace";
      ctx.textAlign = "center";
      ctx.fillText("NO TRAJECTORIES ACTIVE — LAUNCH VIDEO PROCESSING TO GENERATE TRAILS", w / 2, h / 2);
      ctx.textAlign = "start";
    }
  }
}
