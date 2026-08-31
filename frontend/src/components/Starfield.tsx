/**
 * The scattered points GitHub layers over its hero gradient.
 *
 * Built from `radial-gradient` stops at percentage positions rather than a
 * canvas or box-shadows: percentages rescale with the element, so the field
 * covers any viewport without a resize handler and without a third canvas
 * competing for the main thread. Positions come from a seeded PRNG so the sky
 * is identical on every render and every reload.
 */
const LAYERS = [
  { count: 46, size: 1.4, seed: 20260830, min: 0.28, max: 0.75, dur: '4.2s' },
  { count: 26, size: 1.9, seed: 99173, min: 0.4, max: 0.95, dur: '6.1s' },
  { count: 14, size: 2.6, seed: 5511, min: 0.5, max: 1, dur: '8.4s' },
]

function field(count: number, size: number, seed: number, min: number, max: number) {
  let s = seed
  const rnd = () => {
    s = (s * 1664525 + 1013904223) % 4294967296
    return s / 4294967296
  }
  return Array.from({ length: count }, () => {
    const x = (rnd() * 100).toFixed(2)
    const y = (rnd() * 100).toFixed(2)
    const a = (min + rnd() * (max - min)).toFixed(2)
    return `radial-gradient(${size}px ${size}px at ${x}% ${y}%, rgba(255,255,255,${a}), transparent)`
  }).join(', ')
}

export function Starfield({ className = 'hero-stars' }: { className?: string }) {
  return (
    <div className={className} aria-hidden="true">
      {LAYERS.map((l, i) => (
        <span
          key={i}
          style={{
            backgroundImage: field(l.count, l.size, l.seed, l.min, l.max),
            animationDuration: l.dur,
            animationDelay: `${i * -1.7}s`,
          }}
        />
      ))}
    </div>
  )
}
