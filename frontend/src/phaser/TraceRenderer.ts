import Phaser from 'phaser'
import type { BodyMeta, EpisodeTrace, Frame, StaticProp } from '../api/types'
import {
  computeStreetFurniture,
  drawIsoFurniture,
  drawIsoGroundTiles,
  drawIsoIntersectionPatch,
  drawIsoProp,
  isoColorForBody,
  isoFootprint,
  isoProject,
  roadOverlap,
  seedFromId,
} from './isoProps'
import { colorForBody as kindColor, drawProp, isSemanticKind, shade, sizePx } from './props'
import {
  drawIsoFrameEffects,
  drawSideFrameEffects,
  drawSideJoints,
} from './visualOverlays'
import { resolveVisualTheme, type VisualTheme } from './visualTheme'

// The simulation is a 2D side-view physics world (gravity pulls -y, things stack
// and fall). We render it as a straight side view — x to the right, y up — so a
// bridge looks like a bridge and a city like buildings on the ground. World units
// are metres; SCALE is px-per-metre at zoom 1, and the camera auto-fits.
const SCALE = 30

const AGENT_A = 0xa78bfa
const AGENT_B = 0x38bdf8
const NEUTRAL = 0x9aa4b2

function colorForBody(id: string): number {
  const lower = id.toLowerCase()
  if (lower.includes('agent_a')) return AGENT_A
  if (lower.includes('agent_b')) return AGENT_B
  return NEUTRAL
}

function parseHexColor(color: string | null | undefined, fallback: number): number {
  if (!color) return fallback
  const named: Record<string, number> = {
    red: 0xef4444,
    blue: 0x3b82f6,
    green: 0x22c55e,
    yellow: 0xeab308,
    orange: 0xf97316,
  }
  if (named[color.toLowerCase()] != null) return named[color.toLowerCase()]
  const n = Number.parseInt(color.replace('#', ''), 16)
  return Number.isNaN(n) ? fallback : n
}

interface Bounds {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

// Ground-plane bounds for the isometric (citysim) path — (x, z) instead of (x, y).
interface IsoBounds {
  minX: number
  maxX: number
  minZ: number
  maxZ: number
}

/**
 * TraceRenderer renders an EpisodeTrace as a 2D side view. React calls its
 * imperative methods to load a trace, render a frame, and drive the camera.
 */
export class TraceRenderer extends Phaser.Scene {
  static readonly KEY = 'trace'

  private trace: EpisodeTrace | null = null
  private ready = false
  private pendingFrame: number | null = null
  private currentFrame = 0
  private engineeringMode = false
  private reducedMotion = false
  private theme: VisualTheme = resolveVisualTheme()

  private skyLayer!: Phaser.GameObjects.Graphics
  private bgLayer!: Phaser.GameObjects.Graphics
  private staticLayer!: Phaser.GameObjects.Graphics
  private gridLayer!: Phaser.GameObjects.Graphics
  private jointLayer!: Phaser.GameObjects.Graphics
  /** The payload's recent path: drawn under the bodies, rebuilt every frame from the trace. */
  private trailLayer!: Phaser.GameObjects.Graphics
  private bodyLayer!: Phaser.GameObjects.Container
  private effectLayer!: Phaser.GameObjects.Graphics
  private debugLayer!: Phaser.GameObjects.Graphics
  private labelLayer!: Phaser.GameObjects.Container
  private bodies = new Map<string, Phaser.GameObjects.Graphics>()
  /** The body the challenge is about (the crate, the ball), if the trace has one. */
  private payloadId: string | null = null
  /** Whether the camera keeps the payload in view, and where it last looked (screen px). */
  private following = false
  private followAt: { x: number; y: number } | null = null

  constructor() {
    super(TraceRenderer.KEY)
  }

  // Side-view projection: metres -> screen px (y inverted, screen-down positive).
  private static px(x: number, y: number): { sx: number; sy: number } {
    return { sx: x * SCALE, sy: -y * SCALE }
  }

  create(): void {
    // Added first so it always renders behind bgLayer/staticLayer/bodyLayer
    // (insertion order = draw order). Screen-fixed (scroll factor 0) so the
    // sky doesn't pan/zoom with the camera.
    this.skyLayer = this.add.graphics()
    this.skyLayer.setScrollFactor(0)
    this.bgLayer = this.add.graphics()
    this.gridLayer = this.add.graphics()
    this.staticLayer = this.add.graphics()
    this.jointLayer = this.add.graphics()
    this.trailLayer = this.add.graphics()
    this.bodyLayer = this.add.container(0, 0)
    this.effectLayer = this.add.graphics()
    this.debugLayer = this.add.graphics()
    this.labelLayer = this.add.container(0, 0)
    this.ready = true
    // Keep the screen-fixed sky backdrop sized to the viewport across a resize.
    this.scale.on('resize', () => {
      if (!this.trace) return
      if ((this.trace.camera ?? 'side') === 'iso') this.drawIsoSky()
      else this.drawSideSky()
    })
    if (this.trace) {
      this.buildWorld()
      this.renderFrame(this.pendingFrame ?? 0)
      this.pendingFrame = null
    }
  }

  // ── Imperative API (called from React) ───────────────────────────────────

  loadTrace(trace: EpisodeTrace): void {
    this.trace = trace
    this.theme = resolveVisualTheme(
      trace.terrain ?? 'grassland',
      trace.visual_style ?? 'realistic',
    )
    this.currentFrame = 0
    if (!this.ready) {
      this.pendingFrame = 0
      return
    }
    this.buildWorld()
    this.renderFrame(0)
  }

  renderFrame(index: number): void {
    if (!this.ready) {
      this.pendingFrame = index
      return
    }
    const trace = this.trace
    if (!trace || trace.frames.length === 0) return
    this.currentFrame = Math.max(0, Math.min(index, trace.frames.length - 1))
    if ((trace.camera ?? 'side') === 'iso') {
      this.renderIsoFrame(this.currentFrame)
      return
    }
    const frame = trace.frames[this.currentFrame]
    for (const [id, body] of Object.entries(frame.bodies)) {
      let gfx = this.bodies.get(id)
      if (!gfx) {
        this.createBody(id)
        gfx = this.bodies.get(id)
      }
      if (!gfx) continue
      const { sx, sy } = TraceRenderer.px(body.x, body.y)
      gfx.setPosition(sx, sy)
      // Physics angle is CCW in y-up space; screen y is flipped, so negate.
      gfx.setRotation(-body.angle)
    }
    this.renderSideOverlays(frame)
    this.renderTrail()
    this.followPayload(frame)
  }

  /** Keep the payload in view (on) or leave the camera where the person put it (off). */
  setFollow(on: boolean): void {
    this.following = on
    this.followAt = null
    const cam = this.cameras?.main
    if (cam && on && this.trace && (this.trace.camera ?? 'side') !== 'iso') {
      // Closer than the whole-world view, so the crate and the bridge under it fill the frame.
      this.fitToWorld()
      cam.setZoom(Phaser.Math.Clamp(cam.zoom * 1.8, 0.1, 8))
    }
    this.renderFrame(this.currentFrame)
  }

  isFollowing(): boolean {
    return this.following
  }

  panBy(dx: number, dy: number): void {
    const cam = this.cameras?.main
    if (!cam) return
    cam.scrollX -= dx / cam.zoom
    cam.scrollY -= dy / cam.zoom
  }

  zoomBy(factor: number): void {
    const cam = this.cameras?.main
    if (!cam) return
    cam.setZoom(Phaser.Math.Clamp(cam.zoom * factor, 0.1, 8))
  }

  resetCamera(): void {
    this.following = false
    this.followAt = null
    if ((this.trace?.camera ?? 'side') === 'iso') {
      this.isoFitToWorld()
      return
    }
    this.fitToWorld()
  }

  toggleGrid(): void {
    if (this.gridLayer) this.gridLayer.setVisible(!this.gridLayer.visible)
  }

  togglePresentationMode(): 'beauty' | 'engineering' {
    this.engineeringMode = !this.engineeringMode
    this.gridLayer.setVisible(this.engineeringMode)
    this.renderFrame(this.currentFrame)
    return this.engineeringMode ? 'engineering' : 'beauty'
  }

  getPresentationMode(): 'beauty' | 'engineering' {
    return this.engineeringMode ? 'engineering' : 'beauty'
  }

  setReducedMotion(reduced: boolean): void {
    this.reducedMotion = reduced
    this.renderFrame(this.currentFrame)
  }

  // ── Internals ─────────────────────────────────────────────────────────────

  private buildWorld(): void {
    const trace = this.trace
    if (!trace) return

    for (const gfx of this.bodies.values()) gfx.destroy()
    this.bodies.clear()
    this.bodyLayer.removeAll(true)
    this.staticLayer.clear()
    this.gridLayer.clear()
    this.jointLayer.clear()
    this.trailLayer.clear()
    this.bgLayer.clear()
    this.skyLayer.clear()
    this.effectLayer.clear()
    this.debugLayer.clear()
    this.labelLayer.removeAll(true)

    if ((trace.camera ?? 'side') === 'iso') {
      this.buildIsoWorld()
      return
    }

    const bounds = this.worldBounds(trace)
    this.cameras.main.setBackgroundColor(this.theme.skyTop)
    this.drawSideSky()
    this.drawSideEnvironment(bounds, trace.terrain ?? 'grassland')
    this.drawGround(bounds, trace)
    this.drawGrid(bounds)
    for (const prop of trace.world_static ?? []) {
      if (prop.kind === 'ground') continue // we draw a richer ground band below
      if (prop.position && prop.position.length >= 2) this.drawStaticProp(prop)
    }

    const first = trace.frames[0]
    if (first) for (const id of Object.keys(first.bodies)) this.createBody(id)
    this.payloadId = TraceRenderer.findPayload(trace)
    this.followAt = null

    this.gridLayer.setVisible(this.engineeringMode)
    this.fitToWorld(bounds)
  }

  /** The body the challenge moves: one whose kind is a crate or ball, else one named like it. */
  static findPayload(trace: EpisodeTrace): string | null {
    const ids = Object.keys(trace.frames[0]?.bodies ?? {})
    const byKind = ids.find((id) => ['crate', 'ball', 'payload'].includes(trace.body_meta?.[id]?.kind ?? ''))
    return byKind ?? ids.find((id) => /crate|ball|payload|cargo/i.test(id)) ?? null
  }

  /** A fading line along the payload's last two seconds, so its path reads in a still frame. */
  private renderTrail(): void {
    this.trailLayer.clear()
    const trace = this.trace
    const id = this.payloadId
    if (!trace || !id || this.engineeringMode) return
    const dt = trace.dt || 1 / 60
    const span = Math.max(2, Math.round(2.0 / dt))
    const stride = Math.max(1, Math.round(0.03 / dt))
    const start = Math.max(0, this.currentFrame - span)
    let previous: { sx: number; sy: number } | null = null
    for (let i = start; i <= this.currentFrame; i += stride) {
      const body = trace.frames[i]?.bodies[id]
      if (!body) continue
      const point = TraceRenderer.px(body.x, body.y)
      if (previous) {
        const age = (this.currentFrame - i) / span // 0 now, 1 two seconds ago
        this.trailLayer.lineStyle(6 * (1 - age) + 1.5, 0xfbbf24, 0.55 * (1 - age))
        this.trailLayer.lineBetween(previous.sx, previous.sy, point.sx, point.sy)
      }
      previous = point
    }
  }

  /** Ease the camera toward the payload (snapping after a jump in time, as when scrubbing). */
  private followPayload(frame: Frame): void {
    const cam = this.cameras?.main
    const id = this.payloadId
    if (!this.following || !cam || !id) return
    const body = frame.bodies[id]
    if (!body) return
    const target = TraceRenderer.px(body.x, body.y + 1.2)
    const at = this.followAt
    const far = !at || Math.hypot(target.sx - at.x, target.sy - at.y) > 6 * SCALE
    const blend = this.reducedMotion || far ? 1 : 0.18
    const x = at ? at.x + (target.sx - at.x) * blend : target.sx
    const y = at ? at.y + (target.sy - at.y) * blend : target.sy
    this.followAt = { x, y }
    cam.centerOn(x, y)
  }

  /** World extent in metres across terrain + props + first-frame bodies. */
  private worldBounds(trace: EpisodeTrace): Bounds {
    let minX = -8
    let maxX = 8
    let minY = 0
    let maxY = 6
    const grow = (x: number, y: number, rx = 0, ry = 0) => {
      minX = Math.min(minX, x - rx)
      maxX = Math.max(maxX, x + rx)
      minY = Math.min(minY, y - ry)
      maxY = Math.max(maxY, y + ry)
    }
    for (const p of trace.world_static ?? []) {
      if (!p.position || p.position.length < 2) continue
      // Ground spans describe collision coverage, not the interesting scene
      // extent. Fitting a 40m arena floor made a 2m crawler/bin occupy only a
      // handful of pixels. Props, goals and bodies determine camera framing.
      if (p.kind === 'ground') continue
      // Rotated axis-aligned half-extents — a wide flat prop (e.g. a 28m road)
      // must not inflate the Y bound as much as an equally large X bound would
      // (the old `max(w, h)` isotropic radius did exactly that, zooming the
      // whole scene out to fit a phantom square around every long thin prop).
      const w = p.size?.[0] ?? 1
      const h = p.kind === 'segment' ? 0.25 : (p.size?.[1] ?? p.size?.[0] ?? 1)
      const ang = p.angle ?? 0
      const hw = w / 2
      const hh = h / 2
      const rx = Math.abs(hw * Math.cos(ang)) + Math.abs(hh * Math.sin(ang)) + 0.5
      const ry = Math.abs(hw * Math.sin(ang)) + Math.abs(hh * Math.cos(ang)) + 0.5
      grow(p.position[0], p.position[1], rx, ry)
    }
    const first = trace.frames[0]
    if (first) for (const b of Object.values(first.bodies)) grow(b.x, b.y, 1, 1)
    return { minX, maxX, minY, maxY }
  }

  private fitToWorld(bounds?: Bounds): void {
    const cam = this.cameras?.main
    if (!cam || !this.trace) return
    const b = bounds ?? this.worldBounds(this.trace)
    // Frame a little sky above and a strip of ground below so the world reads as
    // a grounded scene rather than a thin band floating in the middle.
    const pad = Math.max(1, (b.maxY - b.minY) * 0.18)
    const a = TraceRenderer.px(b.minX - 0.5, b.maxY + pad) // top-left in screen px
    const c = TraceRenderer.px(b.maxX + 0.5, b.minY - pad * 1.4) // bottom-right
    const worldW = Math.abs(c.sx - a.sx) || 1
    const worldH = Math.abs(c.sy - a.sy) || 1
    const vw = this.scale.width || 800
    const vh = this.scale.height || 600
    const zoom = Phaser.Math.Clamp(Math.min(vw / worldW, vh / worldH) * 0.95, 0.1, 8)
    cam.setZoom(zoom)
    cam.centerOn((a.sx + c.sx) / 2, (a.sy + c.sy) / 2)
  }

  /** Ground is drawn per span (from `world_static` "ground" props), not as one
   * continuous band, so a world with a real gap (a bridge's ravine) shows sky/
   * chasm between cliffs instead of hiding it under a solid floor. */
  private drawSideSky(): void {
    const g = this.skyLayer
    g.clear()
    const width = this.scale.width || 800
    const height = this.scale.height || 600
    g.fillGradientStyle(
      this.theme.skyTop,
      this.theme.skyTop,
      this.theme.skyBottom,
      this.theme.skyBottom,
      1,
    )
    g.fillRect(0, 0, width, height)
    if (this.theme.style === 'blueprint') {
      g.lineStyle(1, this.theme.accent, 0.08)
      for (let x = 0; x < width; x += 32) g.lineBetween(x, 0, x, height)
      for (let y = 0; y < height; y += 32) g.lineBetween(0, y, width, y)
    }
  }

  private drawSideEnvironment(b: Bounds, terrain: string): void {
    const g = this.bgLayer
    const left = (b.minX - 8) * SCALE
    const right = (b.maxX + 8) * SCALE
    const horizon = 0
    const width = right - left

    if (terrain === 'city') {
      this.drawCitySkyline(b)
      return
    }
    if (terrain === 'factory') {
      g.fillStyle(shade(this.theme.haze, 0.5), 0.5)
      for (let i = 0; i < 9; i++) {
        const x = left + (i / 8) * width
        const w = 42 + (i % 3) * 18
        const h = 80 + ((i * 37) % 110)
        g.fillRect(x - w / 2, horizon - h, w, h)
        g.fillRect(x - w * 0.3, horizon - h - 38, w * 0.16, 40)
      }
      g.lineStyle(5, shade(this.theme.haze, 0.7), 0.42)
      g.lineBetween(left, -55, right, -55)
      for (let x = left + 30; x < right; x += 110) {
        g.lineBetween(x, -55, x, -8)
      }
      return
    }
    if (terrain === 'cave') {
      g.fillStyle(0x050609, 0.72)
      g.beginPath()
      g.moveTo(left, -240)
      for (let x = left; x <= right; x += 50) {
        const y = -190 - Math.abs(Math.sin(x * 0.013)) * 90
        g.lineTo(x, y)
      }
      g.lineTo(right, -420)
      g.lineTo(left, -420)
      g.closePath()
      g.fillPath()
      return
    }

    const desert = terrain === 'desert'
    const layers = desert ? 2 : 3
    for (let layer = 0; layer < layers; layer++) {
      const baseY = -10 - layer * 26
      const amplitude = desert ? 28 + layer * 10 : 45 + layer * 22
      g.fillStyle(
        shade(this.theme.haze, 0.5 + layer * 0.14),
        0.24 + layer * 0.12,
      )
      g.beginPath()
      g.moveTo(left, horizon)
      for (let x = left; x <= right; x += 35) {
        const y = baseY - Math.abs(Math.sin(x * 0.009 + layer * 1.7)) * amplitude
        g.lineTo(x, y)
      }
      g.lineTo(right, horizon)
      g.closePath()
      g.fillPath()
    }
    if (!desert) {
      g.fillStyle(0xd9f2ff, 0.42)
      for (let i = 0; i < 5; i++) {
        const x = left + ((i + 0.5) / 5) * width
        const y = -150 - (i % 2) * 35
        g.fillEllipse(x, y, 52, 14)
        g.fillEllipse(x + 22, y - 5, 44, 15)
      }
    }
  }

  private drawGround(b: Bounds, trace: EpisodeTrace): void {
    const g = this.staticLayer
    const top = 0 // y=0 in screen px
    const bottom = -b.minY * SCALE + Math.abs(b.maxY - b.minY) * SCALE + 400

    const spans = (trace.world_static ?? [])
      .filter((p) => p.kind === 'ground' && p.position && p.position.length >= 2)
      .map((p) => {
        const half = (p.size?.[0] ?? 1) / 2
        return { lo: p.position[0] - half, hi: p.position[0] + half }
      })
      .sort((x, y) => x.lo - y.lo)
    const isCliffWorld = trace.kill_y != null && spans.length > 1
    const fillColor = isCliffWorld ? 0x52606c : this.theme.ground

    if (spans.length === 0) {
      // No ground info (shouldn't happen) — fall back to a full-bleed band so
      // the scene never renders as blank sky.
      const left = b.minX * SCALE - 200
      const right = b.maxX * SCALE + 200
      g.fillStyle(fillColor, 1)
      g.fillRect(left, top, right - left, bottom - top)
      this.drawGroundTexture(g, left, right, top, bottom)
      if (isCliffWorld) this.drawRockFace(g, left, right, top, bottom)
      g.lineStyle(3, this.theme.groundEdge, 1)
      g.lineBetween(left, top, right, top)
      return
    }

    for (const span of spans) {
      const left = span.lo * SCALE - 4
      const right = span.hi * SCALE + 4
      g.fillStyle(fillColor, 1)
      g.fillRect(left, top, right - left, bottom - top)
      this.drawGroundTexture(g, left, right, top, bottom)
      if (isCliffWorld) this.drawRockFace(g, left, right, top, bottom)
      g.lineStyle(3, this.theme.groundEdge, 1)
      g.lineBetween(left, top, right, top)
      if ((trace.terrain ?? 'grassland') === 'grassland') {
        if (isCliffWorld) {
          g.fillStyle(this.theme.ground, 1)
          g.fillRect(left, top, right - left, 10)
        }
        g.fillStyle(shade(this.theme.ground, 1.25), 0.75)
        for (let x = left + 4; x < right - 4; x += 13) {
          const blade = 3 + ((x / 13) % 3)
          g.fillTriangle(x, top, x + 3, top, x + 1.5, top - blade)
        }
      }
    }

    // Ravine: a hazard/water band filling the horizontal gap between
    // consecutive spans, from the horizon down to kill_y (or a sensible
    // default depth when the world didn't declare one).
    const chasmFloorY = trace.kill_y ?? Math.min(b.minY - 2, -4)
    for (let i = 0; i < spans.length - 1; i++) {
      const gapLo = spans[i].hi
      const gapHi = spans[i + 1].lo
      if (gapHi <= gapLo) continue
      this.drawChasm(gapLo * SCALE, gapHi * SCALE, top, -chasmFloorY * SCALE)
    }
  }

  private drawRockFace(
    g: Phaser.GameObjects.Graphics,
    left: number,
    right: number,
    top: number,
    bottom: number,
  ): void {
    const depth = Math.min(bottom - top, 270)
    g.lineStyle(2, 0x2d3944, 0.48)
    for (let y = top + 25; y < top + depth; y += 32) {
      const offset = (Math.floor(y / 32) % 2) * 21
      for (let x = left + offset; x < right; x += 64) {
        const end = Math.min(x + 42 + ((x + y) % 17), right)
        g.lineBetween(x, y, end, y + ((x / 10) % 3) - 1)
      }
    }
    g.fillStyle(0x8c9aa7, 0.18)
    for (let x = left + 18; x < right; x += 75) {
      g.fillTriangle(x, top + 18, x + 18, top + 8, x + 32, top + 28)
    }
  }

  private drawGroundTexture(
    g: Phaser.GameObjects.Graphics,
    left: number,
    right: number,
    top: number,
    bottom: number,
  ): void {
    const depth = Math.min(bottom - top, 210)
    g.lineStyle(1, shade(this.theme.groundEdge, 1.35), 0.22)
    for (let y = top + 18; y < top + depth; y += 22) {
      const offset = (Math.floor(y / 22) % 2) * 13
      for (let x = left + offset; x < right; x += 52) {
        g.lineBetween(x, y, Math.min(x + 34, right), y + 3)
      }
    }
  }

  /** Hazard band for a ground gap: dark water fill + a warning-colored top edge
   * so the ravine reads as "do not fall here", not empty background. */
  private drawChasm(leftPx: number, rightPx: number, topPx: number, bottomPx: number): void {
    const g = this.staticLayer
    g.fillStyle(0x082334, 1)
    g.fillRect(leftPx, topPx, rightPx - leftPx, bottomPx - topPx)
    g.fillStyle(0x1c5a7a, 0.5)
    for (let x = leftPx; x < rightPx; x += 14) {
      g.fillRect(x, topPx + 6, 8, 3)
    }
    g.fillStyle(0x70d6ff, 0.22)
    for (let x = leftPx + 4; x < rightPx; x += 22) {
      g.fillCircle(x, topPx + 4 + Math.sin(x * 0.05) * 2, 2)
    }
    g.lineStyle(2, this.theme.hazard, 0.9)
    g.lineBetween(leftPx, topPx, rightPx, topPx)
  }

  private drawGrid(b: Bounds): void {
    const g = this.gridLayer
    g.lineStyle(1, this.theme.grid, this.engineeringMode ? 0.58 : 0.16)
    const x0 = Math.floor(b.minX) - 1
    const x1 = Math.ceil(b.maxX) + 1
    const y0 = Math.floor(b.minY) - 1
    const y1 = Math.ceil(b.maxY) + 1
    for (let x = x0; x <= x1; x += 2) {
      g.lineBetween(x * SCALE, -y0 * SCALE, x * SCALE, -y1 * SCALE)
    }
    for (let y = y0; y <= y1; y += 2) {
      g.lineBetween(x0 * SCALE, -y * SCALE, x1 * SCALE, -y * SCALE)
    }
  }

  /** Faint parallax building silhouettes behind the play area, for terrain=city. */
  private drawCitySkyline(b: Bounds): void {
    const g = this.bgLayer
    const pseudoRandom = (seed: number) => {
      const x = Math.sin(seed * 12.9898) * 43758.5453
      return x - Math.floor(x)
    }
    const spanL = b.minX - 6
    const spanR = b.maxX + 6
    const width = Math.max(1, spanR - spanL)
    const count = 14
    g.fillStyle(shade(this.theme.haze, 0.55), 0.48)
    for (let i = 0; i < count; i++) {
      const t = i / count
      const bx = spanL + t * width + (pseudoRandom(i) - 0.5) * (width / count) * 0.6
      const bw = 1.5 + pseudoRandom(i + 50) * 2.0
      const bh = 3 + pseudoRandom(i + 100) * 8
      const topLeft = TraceRenderer.px(bx - bw / 2, bh)
      const bottomRight = TraceRenderer.px(bx + bw / 2, 0)
      g.fillRect(
        topLeft.sx,
        topLeft.sy,
        bottomRight.sx - topLeft.sx,
        bottomRight.sy - topLeft.sy,
      )
      if (i % 2 === 0) {
        g.fillStyle(this.theme.accent, 0.08)
        const cols = Math.max(1, Math.floor(bw))
        for (let c = 0; c < cols; c++) {
          g.fillRect(
            topLeft.sx + 8 + c * 13,
            topLeft.sy + 12,
            4,
            Math.max(4, (bottomRight.sy - topLeft.sy) * 0.6),
          )
        }
        g.fillStyle(shade(this.theme.haze, 0.55), 0.48)
      }
    }
  }

  /** Draw a static prop to scale, rotated by its angle — a recognizable shape
   * for a semantic `kind` (house/road/tree/…), else a plain box/circle/segment. */
  private drawStaticProp(prop: StaticProp): void {
    const g = this.staticLayer
    const [px, py] = prop.position
    const ang = prop.angle ?? 0

    // Semantic kind (house/wall/bin/…) → a recognizable procedural prop.
    if (isSemanticKind(prop.kind)) {
      // The real geometry (box/circle/segment) — a beam/ramp/wall is a thin
      // segment sized by length alone, not a square built from that length.
      const meta = {
        shape: prop.shape ?? 'box',
        size: prop.size,
        color: prop.color,
        kind: prop.kind,
        created_by: prop.created_by,
        visual: prop.visual,
      } as BodyMeta
      const { w, h } = sizePx(meta, SCALE)
      const { sx, sy } = TraceRenderer.px(px, py)
      g.save()
      g.translateCanvas(sx, sy)
      g.rotateCanvas(-ang)
      if (!['road', 'park', 'plaza', 'water', 'goal'].includes(prop.kind)) {
        g.fillStyle(0x000000, this.theme.shadowAlpha)
        g.fillEllipse(5, h / 2 + 4, Math.max(8, w * 0.9), Math.max(4, h * 0.13))
      }
      drawProp(g, prop.kind, w, h, kindColor(prop.id, meta), {
        ...prop.visual,
        style: this.theme.style,
        time: this.trace?.frames[this.currentFrame]?.t ?? 0,
        shape: meta.shape,
      })
      g.restore()
      return
    }

    const w = prop.size?.[0] ?? 1
    const h = prop.kind === 'segment' ? 0.25 : (prop.size?.[1] ?? prop.size?.[0] ?? 1)
    const color = parseHexColor(prop.color, NEUTRAL)
    g.fillStyle(color, 1)
    g.lineStyle(1.5, this.theme.outline, 0.6)

    if (prop.kind === 'circle') {
      const r = (prop.size?.[0] ?? 0.5) * SCALE
      const { sx, sy } = TraceRenderer.px(px, py)
      g.fillCircle(sx, sy, r)
      g.strokeCircle(sx, sy, r)
      return
    }

    // box or segment → a (possibly thin) rotated rectangle.
    this.fillRotatedRect(g, px, py, w, h, ang)
  }

  /** Fill + outline a w×h rect (metres) centred at (px,py), rotated by `ang`. */
  private fillRotatedRect(
    g: Phaser.GameObjects.Graphics,
    px: number,
    py: number,
    w: number,
    h: number,
    ang: number,
  ): void {
    const hw = w / 2
    const hh = h / 2
    const cos = Math.cos(ang)
    const sin = Math.sin(ang)
    const corner = (dx: number, dy: number) => {
      const rx = dx * cos - dy * sin
      const ry = dx * sin + dy * cos
      return TraceRenderer.px(px + rx, py + ry)
    }
    const pts = [corner(-hw, hh), corner(hw, hh), corner(hw, -hh), corner(-hw, -hh)]
    g.beginPath()
    g.moveTo(pts[0].sx, pts[0].sy)
    for (let i = 1; i < pts.length; i++) g.lineTo(pts[i].sx, pts[i].sy)
    g.closePath()
    g.fillPath()
    g.strokePath()
  }

  /** Create a dynamic body's graphics, drawn to its real shape/size/colour. */
  private createBody(id: string): void {
    const meta: BodyMeta | undefined = this.trace?.body_meta?.[id]
    const g = this.add.graphics()

    // Semantic kind (house/tower/tree/…) → a recognizable procedural prop.
    if (isSemanticKind(meta?.kind)) {
      const { w, h } = sizePx(meta, SCALE)
      drawProp(g, meta?.kind, w, h, kindColor(id, meta), {
        ...meta?.visual,
        style: this.theme.style,
        shape: meta?.shape,
      })
      this.bodyLayer.add(g)
      this.bodies.set(id, g)
      return
    }

    const fill = parseHexColor(meta?.color, colorForBody(id))
    g.fillStyle(fill, 1)
    g.lineStyle(2, 0xffffff, 0.4)

    const shape = meta?.shape ?? 'box'
    if (shape === 'circle') {
      const r = (meta?.size?.[0] ?? 0.5) * SCALE
      g.fillCircle(0, 0, r)
      g.lineStyle(2, this.theme.outline, 0.5)
      g.strokeCircle(0, 0, r)
      // A spoke so rotation (rolling) is visible.
      g.lineStyle(2, 0xffffff, 0.5)
      g.lineBetween(0, 0, r, 0)
    } else if (shape === 'segment') {
      const len = (meta?.size?.[0] ?? 1) * SCALE
      const th = 0.25 * SCALE
      g.fillRect(-len / 2, -th / 2, len, th)
      g.lineStyle(2, this.theme.outline, 0.5)
      g.strokeRect(-len / 2, -th / 2, len, th)
    } else {
      const w = (meta?.size?.[0] ?? 1) * SCALE
      const h = (meta?.size?.[1] ?? meta?.size?.[0] ?? 1) * SCALE
      g.fillRect(-w / 2, -h / 2, w, h)
      g.lineStyle(2, this.theme.outline, 0.5)
      g.strokeRect(-w / 2, -h / 2, w, h)
    }

    this.bodyLayer.add(g)
    this.bodies.set(id, g)
  }

  private renderSideOverlays(frame: Frame): void {
    const trace = this.trace
    if (!trace) return
    const previous = trace.frames[this.currentFrame - 1]
    const time = this.reducedMotion ? 0 : frame.t
    this.jointLayer.clear()
    this.effectLayer.clear()
    this.debugLayer.clear()
    this.labelLayer.removeAll(true)

    // Dynamic contact shadows stay tied to the ground, which makes height and
    // jumping/falling much easier to read than a floating silhouette.
    for (const [id, body] of Object.entries(frame.bodies)) {
      const meta = trace.body_meta?.[id]
      const { w } = sizePx(meta, SCALE)
      const ground = TraceRenderer.px(body.x, 0)
      const height = Math.max(0, body.y)
      const alpha = this.theme.shadowAlpha * Math.max(0.08, 1 - height / 12)
      this.jointLayer.fillStyle(0x000000, alpha)
      this.jointLayer.fillEllipse(
        ground.sx + 5,
        ground.sy + 3,
        Math.max(8, w * Math.max(0.25, 1 - height / 18)),
        Math.max(3, w * 0.12),
      )
    }

    drawSideJoints(
      this.jointLayer,
      trace,
      frame,
      TraceRenderer.px,
      time,
      this.engineeringMode,
    )
    this.drawSideAmbientEffects(frame, previous)
    drawSideFrameEffects(
      this.effectLayer,
      trace,
      frame,
      previous,
      TraceRenderer.px,
      this.engineeringMode,
    )
    if (this.engineeringMode) this.drawSideEngineeringOverlay(frame)
  }

  private drawSideAmbientEffects(frame: Frame, previous: Frame | undefined): void {
    const trace = this.trace
    if (!trace) return
    const time = this.reducedMotion ? 0 : frame.t
    const g = this.effectLayer

    for (const prop of trace.world_static) {
      if (prop.kind === 'water') {
        const [x, y] = prop.position
        const w = (prop.size?.[0] ?? 1) * SCALE
        const h = Math.max(6, (prop.size?.[1] ?? 0.25) * SCALE)
        const center = TraceRenderer.px(x, y)
        g.lineStyle(1.5, 0x9eeaff, 0.45)
        for (let row = 0; row < 3; row++) {
          const yy = center.sy - h / 2 + ((row + 1) * h) / 4
          const segments = Math.max(4, Math.floor(w / 24))
          for (let segment = 0; segment < segments; segment++) {
            const x0 = center.sx - w / 2 + (segment * w) / segments
            const x1 = center.sx - w / 2 + ((segment + 0.65) * w) / segments
            g.lineBetween(
              x0,
              yy + Math.sin(segment + time * 3 + row) * 2,
              x1,
              yy,
            )
          }
        }
      }
      if (prop.kind === 'goal') {
        const center = TraceRenderer.px(prop.position[0], prop.position[1])
        const pulse = this.reducedMotion ? 0 : Math.sin(time * 4) * 4
        g.lineStyle(2, 0x34d399, 0.45)
        g.strokeCircle(center.sx, center.sy, 18 + pulse)
      }
    }

    if (!previous || this.reducedMotion) return
    for (const [id, body] of Object.entries(frame.bodies)) {
      const before = previous.bodies[id]
      if (!before) continue
      const speed = Math.hypot(body.x - before.x, body.y - before.y) / Math.max(trace.dt, 0.001)
      if (speed < 1.1 || body.y > 1.2) continue
      const point = TraceRenderer.px(body.x, Math.max(0.05, body.y - 0.4))
      g.fillStyle(0xd6c4a1, Math.min(0.45, speed * 0.04))
      for (let i = 0; i < 3; i++) {
        g.fillCircle(point.sx - 5 - i * 5, point.sy + (i % 2) * 2, 2.5 + i)
      }
    }
  }

  private drawSideEngineeringOverlay(frame: Frame): void {
    const trace = this.trace
    if (!trace) return
    const g = this.debugLayer
    for (const [id, body] of Object.entries(frame.bodies)) {
      const meta = trace.body_meta?.[id]
      const { w, h } = sizePx(meta, SCALE)
      const point = TraceRenderer.px(body.x, body.y)
      g.save()
      g.translateCanvas(point.sx, point.sy)
      g.rotateCanvas(-body.angle)
      g.lineStyle(1, 0x67e8f9, 0.72)
      if (meta?.shape === 'circle') g.strokeCircle(0, 0, w / 2)
      else g.strokeRect(-w / 2, -h / 2, w, h)
      g.lineStyle(1, 0xffffff, 0.55)
      g.lineBetween(-5, 0, 5, 0)
      g.lineBetween(0, -5, 0, 5)
      g.restore()

      const label = this.add.text(point.sx + 7, point.sy - h / 2 - 14, `${id} · ${meta?.kind ?? meta?.shape ?? 'body'}`, {
        fontFamily: 'monospace',
        fontSize: '10px',
        color: '#d9f7ff',
        backgroundColor: '#07131dcc',
        padding: { x: 3, y: 2 },
      })
      this.labelLayer.add(label)
    }
  }

  // ── Isometric (citysim) path ──────────────────────────────────────────────
  // A separate code path from the side-view methods above: ground-plane (x, z)
  // instead of (x, y), painter's-algorithm depth sorting, and extruded-box
  // props via isoProps.ts. Kept parallel rather than merged into the side-view
  // methods so the well-exercised physics replay path is untouched.

  private isoWorldBounds(trace: EpisodeTrace): IsoBounds {
    let minX = -8
    let maxX = 8
    let minZ = -8
    let maxZ = 8
    const grow = (x: number, z: number, r = 1) => {
      minX = Math.min(minX, x - r)
      maxX = Math.max(maxX, x + r)
      minZ = Math.min(minZ, z - r)
      maxZ = Math.max(maxZ, z + r)
    }
    for (const p of trace.world_static ?? []) {
      if (!p.position || p.position.length < 1) continue
      const { w, d } = isoFootprint(p.size)
      grow(p.position[0], p.z ?? 0, Math.max(w, d) / 2 + 0.5)
    }
    const first = trace.frames[0]
    if (first) for (const b of Object.values(first.bodies)) grow(b.x, b.z ?? 0, 1)
    return { minX, maxX, minZ, maxZ }
  }

  private isoMaxHeight(trace: EpisodeTrace): number {
    let maxHeight = 4
    for (const p of trace.world_static ?? []) {
      const { h } = isoFootprint(p.size)
      maxHeight = Math.max(maxHeight, h)
    }
    return maxHeight
  }

  private isoFitToWorld(bounds?: IsoBounds): void {
    const cam = this.cameras?.main
    const trace = this.trace
    if (!cam || !trace) return
    const b = bounds ?? this.isoWorldBounds(trace)
    const maxHeight = this.isoMaxHeight(trace)
    const corners = [
      isoProject(b.minX, b.minZ, 0),
      isoProject(b.maxX, b.minZ, 0),
      isoProject(b.minX, b.maxZ, 0),
      isoProject(b.maxX, b.maxZ, 0),
      isoProject(b.minX, b.minZ, maxHeight),
      isoProject(b.maxX, b.minZ, maxHeight),
      isoProject(b.minX, b.maxZ, maxHeight),
      isoProject(b.maxX, b.maxZ, maxHeight),
    ]
    const minSx = Math.min(...corners.map((p) => p.sx))
    const maxSx = Math.max(...corners.map((p) => p.sx))
    const minSy = Math.min(...corners.map((p) => p.sy))
    const maxSy = Math.max(...corners.map((p) => p.sy))
    const pad = 60
    const worldW = Math.max(maxSx - minSx + pad * 2, 1)
    const worldH = Math.max(maxSy - minSy + pad * 2, 1)
    const vw = this.scale.width || 800
    const vh = this.scale.height || 600
    const zoom = Phaser.Math.Clamp(Math.min(vw / worldW, vh / worldH) * 0.95, 0.1, 8)
    cam.setZoom(zoom)
    cam.centerOn((minSx + maxSx) / 2, (minSy + maxSy) / 2)
  }

  /** Screen-fixed vertical sky gradient behind the whole iso scene. */
  private drawIsoSky(): void {
    const g = this.skyLayer
    g.clear()
    const w = this.scale.width || 800
    const h = this.scale.height || 600
    g.fillGradientStyle(
      this.theme.skyTop,
      this.theme.skyTop,
      this.theme.skyBottom,
      this.theme.skyBottom,
      1,
    )
    g.fillRect(0, 0, w, h)
    g.fillStyle(this.theme.haze, 0.18)
    g.fillEllipse(w * 0.74, h * 0.23, Math.min(w, h) * 0.3, Math.min(w, h) * 0.08)
    if (this.theme.style === 'neon_lab') {
      g.lineStyle(1, this.theme.accent, 0.1)
      for (let y = h * 0.45; y < h; y += 18) g.lineBetween(0, y, w, y)
    }
  }

  /** Textured ground (grass mottling + sidewalks bordering roads), plus a
   * defining outer edge so the world reads as a bounded plot, not a void. */
  private drawIsoGround(b: IsoBounds, roads: StaticProp[]): void {
    const g = this.staticLayer
    drawIsoGroundTiles(g, b, this.theme.ground, roads)

    const corners = [
      isoProject(b.minX, b.minZ, 0),
      isoProject(b.maxX, b.minZ, 0),
      isoProject(b.maxX, b.maxZ, 0),
      isoProject(b.minX, b.maxZ, 0),
    ]
    g.lineStyle(2, this.theme.groundEdge, 0.7)
    g.beginPath()
    g.moveTo(corners[0].sx, corners[0].sy)
    for (let i = 1; i < corners.length; i++) g.lineTo(corners[i].sx, corners[i].sy)
    g.closePath()
    g.strokePath()
  }

  /** Draw one static prop's extruded iso shape, translated to its ground point. */
  private drawIsoStaticProp(prop: StaticProp, time = 0): void {
    const g = this.staticLayer
    const { w, d, h } = isoFootprint(prop.size)
    const color = isoColorForBody(prop.id, prop)
    const origin = isoProject(prop.position[0] ?? 0, prop.z ?? 0, 0)
    g.save()
    g.translateCanvas(origin.sx, origin.sy)
    drawIsoProp(g, prop.kind, w, d, h, color, seedFromId(prop.id), {
      ...prop.visual,
      style: this.theme.style,
      time: this.reducedMotion ? 0 : time,
      shadowAlpha: this.theme.shadowAlpha,
    })
    g.restore()
  }

  /** Paved patches over every road-road intersection, drawn after all road
   * props so they sit cleanly on top of both crossing segments' markings. */
  private drawIsoIntersections(roads: StaticProp[]): void {
    const g = this.staticLayer
    for (let i = 0; i < roads.length; i++) {
      for (let j = i + 1; j < roads.length; j++) {
        const overlap = roadOverlap(roads[i], roads[j])
        if (!overlap) continue
        const topY = Math.max(isoFootprint(roads[i].size).h, isoFootprint(roads[j].size).h)
        drawIsoIntersectionPatch(g, overlap.cx, overlap.cz, overlap.w, overlap.d, topY)
      }
    }
  }

  /** Streetlights/parked cars scattered along road edges — decorative only,
   * derived client-side from the trace's own roads/buildings (never sent to
   * or from the backend), same spirit as the side view's parallax skyline. */
  private drawIsoStreetFurniture(roads: StaticProp[], buildings: StaticProp[]): void {
    const g = this.staticLayer
    const items = computeStreetFurniture(roads, buildings)
    const sorted = [...items].sort((a, b) => a.x + a.z - (b.x + b.z))
    sorted.forEach((item, i) => {
      const origin = isoProject(item.x, item.z, 0)
      g.save()
      g.translateCanvas(origin.sx, origin.sy)
      drawIsoFurniture(g, item, i)
      g.restore()
    })
  }

  private buildIsoWorld(): void {
    const trace = this.trace
    if (!trace) return

    const bounds = this.isoWorldBounds(trace)
    this.cameras.main.setBackgroundColor(this.theme.skyTop)
    this.drawIsoSky()

    const allProps = (trace.world_static ?? []).filter((p) => p.position && p.position.length >= 1)
    const roads = allProps.filter((p) => p.kind === 'road')
    const buildings = allProps.filter((p) => p.kind !== 'road')

    this.drawIsoGround(bounds, roads)

    // Painter's algorithm: draw back-to-front by ground-plane depth (x + z),
    // so nearer structures correctly occlude farther ones.
    const props = [...allProps].sort(
      (a, b) => a.position[0] + (a.z ?? 0) - (b.position[0] + (b.z ?? 0)),
    )
    for (const prop of props) this.drawIsoStaticProp(prop)

    this.drawIsoIntersections(roads)
    this.drawIsoStreetFurniture(roads, buildings)

    const first = trace.frames[0]
    if (first) {
      const ids = Object.keys(first.bodies).sort((a, b) => {
        const ba = first.bodies[a]
        const bb = first.bodies[b]
        return ba.x + (ba.z ?? 0) - (bb.x + (bb.z ?? 0))
      })
      for (const id of ids) this.createIsoBody(id)
    }

    this.gridLayer.setVisible(this.engineeringMode)
    this.isoFitToWorld(bounds)
  }

  /** Create a dynamic iso body's graphics (unused by CityEngine today — it has
   * no rigid-body motion — but supported for a future engine that animates
   * ground-plane movement, e.g. cars/pedestrians). */
  private createIsoBody(id: string): void {
    const meta: BodyMeta | undefined = this.trace?.body_meta?.[id]
    const g = this.add.graphics()
    const { w, d, h } = isoFootprint(meta?.size)
    const color = isoColorForBody(id, meta)
    drawIsoProp(g, meta?.kind, w, d, h, color, seedFromId(id), {
      ...meta?.visual,
      style: this.theme.style,
      shadowAlpha: this.theme.shadowAlpha,
    })
    this.bodyLayer.add(g)
    this.bodies.set(id, g)
  }

  private renderIsoOverlays(frame: Frame): void {
    const trace = this.trace
    if (!trace) return
    const previous = trace.frames[this.currentFrame - 1]
    this.jointLayer.clear()
    this.effectLayer.clear()
    this.debugLayer.clear()
    this.labelLayer.removeAll(true)

    this.drawIsoAmbientEffects(frame)
    drawIsoFrameEffects(this.effectLayer, frame, previous, this.engineeringMode)
    if (this.engineeringMode) this.drawIsoEngineeringOverlay()
    this.drawCityMetrics(frame)
  }

  private drawIsoAmbientEffects(frame: Frame): void {
    const trace = this.trace
    if (!trace || this.reducedMotion) return
    const roads = trace.world_static.filter((prop) => prop.kind === 'road')
    const time = frame.t
    const g = this.effectLayer

    // Sparse moving traffic provides scale and life without adding simulated
    // bodies or changing city scoring. Paths are derived deterministically
    // from trace roads and current replay time.
    roads.slice(0, 8).forEach((road, index) => {
      const { w, d, h } = isoFootprint(road.size)
      const alongX = w >= d
      const length = alongX ? w : d
      const phase = ((time * (0.7 + (index % 3) * 0.16) + index * 2.7) % (length + 2)) - length / 2
      const x = (road.position[0] ?? 0) + (alongX ? phase : 0)
      const z = (road.z ?? 0) + (alongX ? 0 : phase)
      const point = isoProject(x, z, h + 0.15)
      g.fillStyle(index % 2 === 0 ? 0xef4444 : 0x60a5fa, 0.9)
      g.fillRoundedRect(point.sx - 5, point.sy - 3, 10, 6, 2)
      g.fillStyle(0xf8fafc, 0.7)
      g.fillRect(point.sx - 1, point.sy - 2, 3, 2)
    })

    for (const prop of trace.world_static) {
      if (prop.kind !== 'fountain') continue
      const { h } = isoFootprint(prop.size)
      const center = isoProject(prop.position[0], prop.z ?? 0, h + 0.25)
      const pulse = 8 + Math.sin(time * 4) * 2
      g.lineStyle(1.5, 0xa5f3fc, 0.65)
      g.strokeEllipse(center.sx, center.sy, pulse * 2.2, pulse)
    }
  }

  private drawIsoEngineeringOverlay(): void {
    const trace = this.trace
    if (!trace) return
    const g = this.debugLayer
    const maxLabels = trace.world_static.length > 100 ? 40 : 100
    trace.world_static.slice(0, maxLabels).forEach((prop) => {
      const { w, d, h } = isoFootprint(prop.size)
      const cx = prop.position[0] ?? 0
      const cz = prop.z ?? 0
      const corners = [
        isoProject(cx - w / 2, cz - d / 2, 0.03),
        isoProject(cx + w / 2, cz - d / 2, 0.03),
        isoProject(cx + w / 2, cz + d / 2, 0.03),
        isoProject(cx - w / 2, cz + d / 2, 0.03),
      ]
      g.lineStyle(1, 0x67e8f9, 0.6)
      g.beginPath()
      g.moveTo(corners[0].sx, corners[0].sy)
      corners.slice(1).forEach((corner) => g.lineTo(corner.sx, corner.sy))
      g.closePath()
      g.strokePath()
      const top = isoProject(cx, cz, h)
      const label = this.add.text(top.sx + 5, top.sy - 12, `${prop.id}\n${prop.kind}`, {
        fontFamily: 'monospace',
        fontSize: '9px',
        color: '#d9f7ff',
        backgroundColor: '#07131dcc',
        padding: { x: 3, y: 2 },
      })
      this.labelLayer.add(label)
    })
  }

  private drawCityMetrics(frame: Frame): void {
    const tick = (frame.events ?? []).find((event) => event.type === 'city_tick')
    if (!tick) return
    const values = tick as Record<string, unknown>
    const format = (key: string, digits = 0) => {
      const value = values[key]
      return typeof value === 'number' ? value.toFixed(digits) : '—'
    }
    const happinessRaw = values.happiness
    const happiness =
      typeof happinessRaw === 'number' ? `${Math.round(happinessRaw * 100)}%` : '—'
    const text = this.add.text(
      this.cameras.main.scrollX + 14 / this.cameras.main.zoom,
      this.cameras.main.scrollY + 14 / this.cameras.main.zoom,
      `CITY PULSE  ·  POP ${format('population')}\nBUDGET ${format('budget', 0)}  ·  HAPPY ${happiness}`,
      {
        fontFamily: 'monospace',
        fontSize: '11px',
        color: '#e8fbff',
        backgroundColor: '#0b1424dd',
        padding: { x: 8, y: 6 },
      },
    )
    text.setScale(1 / this.cameras.main.zoom)
    this.labelLayer.add(text)
  }

  private renderIsoFrame(index: number): void {
    const trace = this.trace
    if (!trace || trace.frames.length === 0) return
    const clamped = Math.max(0, Math.min(index, trace.frames.length - 1))
    const frame = trace.frames[clamped]
    for (const [id, body] of Object.entries(frame.bodies)) {
      let gfx = this.bodies.get(id)
      if (!gfx) {
        this.createIsoBody(id)
        gfx = this.bodies.get(id)
      }
      if (!gfx) continue
      const { sx, sy } = isoProject(body.x, body.z ?? 0, 0)
      gfx.setPosition(sx, sy)
    }
    this.renderIsoOverlays(frame)
  }
}
