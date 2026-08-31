/**
 * The hero graphic: a buggy running over scrolling terrain.
 *
 * Everything moves in CSS (see site.css) rather than SMIL or JS — one compositor
 * job, nothing on the main thread, and a single prefers-reduced-motion block
 * stops the whole scene. The illusion is only three tricks: the car bobs in
 * place, the wheels spin, and the ground slides under it.
 *
 * The ground is drawn twice, the second copy offset by exactly one tile width
 * (TILE). The strip animates from 0 to -TILE and restarts, so the seam always
 * lands on identical geometry and the loop is invisible.
 */
const TILE = 480

/** One tile of ground. Starts and ends at the same y so copies join cleanly. */
const GROUND = `M0 44 C 40 44, 55 22, 95 24 S 150 52, 190 46 S 250 18, 292 28
  S 350 54, 392 44 S 450 30, ${TILE} 44 L ${TILE} 90 L 0 90 Z`

const RIDGE = `M0 30 L 60 6 L 104 26 L 150 2 L 210 30 L 268 10 L 320 30
  L 380 8 L 430 28 L ${TILE} 14 L ${TILE} 80 L 0 80 Z`

function Wheel({ cx, cy }: { cx: number; cy: number }) {
  return (
    <g className="scene-wheel" style={{ transformOrigin: `${cx}px ${cy}px` }}>
      {/* Dashes around the rim read as knobby tread for the price of one circle. */}
      <circle cx={cx} cy={cy} r={26} className="tyre" />
      <circle cx={cx} cy={cy} r={22} className="tread" strokeDasharray="7 8" />
      <circle cx={cx} cy={cy} r={12} className="rim" />
      <path
        d={`M${cx - 12} ${cy} H${cx + 12} M${cx} ${cy - 12} V${cy + 12}`}
        className="spokes"
      />
    </g>
  )
}

export function BajaScene() {
  return (
    <svg className="scene" viewBox="0 0 480 260" role="img" aria-label="A Baja SAE buggy driving over rough terrain">
      <defs>
        <linearGradient id="scene-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#171a21" />
          <stop offset="100%" stopColor="#0e0f12" />
        </linearGradient>
        <linearGradient id="scene-sun" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ff6a1a" stopOpacity="0.30" />
          <stop offset="100%" stopColor="#ff6a1a" stopOpacity="0" />
        </linearGradient>
      </defs>

      <rect width="480" height="260" fill="url(#scene-sky)" />
      <circle cx="360" cy="92" r="46" fill="url(#scene-sun)" />
      <circle cx="360" cy="92" r="17" className="scene-sun-core" />

      {/* Far ridge: same trick as the ground, slower, so it reads as distance. */}
      <g className="scene-ridge" transform="translate(0 118)">
        <path d={RIDGE} />
        <path d={RIDGE} transform={`translate(${TILE} 0)`} />
      </g>

      <g className="scene-car">
        <g className="scene-car-body" transform="translate(240 150)">
          {/* suspension arms, drawn under the tub */}
          <path d="M-44 24 L-72 38 M50 24 L78 38" className="arm" />

          {/* chassis tub */}
          <path d="M-88 16 L-52 -2 L30 -6 L70 12 L106 20 L106 32 L-84 32 Z" className="tub" />

          {/* roll cage */}
          <path
            d="M-70 14 L-48 -44 L34 -50 L74 8 M-48 -44 L-6 -47 M-6 -47 L-2 -8 M34 -50 L74 8 L106 22"
            className="cage"
          />

          {/* driver */}
          <circle cx="-14" cy="-22" r="12" className="helmet" />
          <path d="M-26 -20 h24" className="visor" />

          <Wheel cx={-72} cy={38} />
          <Wheel cx={78} cy={38} />
        </g>

        {/* Kicked up behind the rear wheel. Staggered in CSS, not here. */}
        <g className="scene-dust">
          <circle cx="150" cy="186" r="7" />
          <circle cx="132" cy="180" r="5" />
          <circle cx="118" cy="188" r="9" />
          <circle cx="100" cy="178" r="6" />
        </g>
      </g>

      <g className="scene-ground" transform="translate(0 170)">
        <path d={GROUND} />
        <path d={GROUND} transform={`translate(${TILE} 0)`} />
      </g>
    </svg>
  )
}
