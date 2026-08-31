import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from 'react'
import {
  Box3,
  DoubleSide,
  Group,
  Mesh,
  MeshStandardMaterial,
  PMREMGenerator,
  PointLight,
  Vector3,
  type Object3D,
} from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'

import { HeroCarFrames } from './HeroCarFrames'

const MODEL = '/models/buggy-hero.glb'
/** Decimated twin. The parts are gpu-instanced, so a phone processes ~580k
 *  vertices per pass at full detail even though only 81k are uploaded; this
 *  build cuts that to ~259k. Chosen by viewport and pointer type, which is the
 *  honest signal for "phone" — deviceMemory is unavailable on iOS. */
const MODEL_LIGHT = '/models/buggy-mobile.glb'
const LIGHT_QUERY = '(max-width: 900px), (pointer: coarse)'
const wantsLight = () =>
  typeof window !== 'undefined' && window.matchMedia(LIGHT_QUERY).matches
/** Rotation (radians) at which the car faces the camera. */
const FRONT = 0
const QUARTER = Math.PI / 2
/** Scroll turns a quarter onto the profile, then the car leaves. */
const SCROLL_SPIN = QUARTER
const SPIN_END = 0.42
/** Turning +90deg from FRONT points the nose at screen RIGHT, so it leaves to
 *  the right. (The GLB winds the opposite way to the pre-rendered turntable —
 *  that mismatch is what made this read as reverse.) */
const EXIT_DIR = 1
const EXIT_DISTANCE = 11
/** Once the spin lands side-on the car leaves on its own clock, not on the
 *  scrollbar — the visitor triggers the departure, they do not drag it. */
const DRIVE_MS = 1150
const INTRO_MS = 2300
const INTRO_TURNS = 1.5
/** Translucent amber body. depthWrite is off so overlapping shells accumulate
 *  instead of occluding each other — that build-up is what reads as glass/glow,
 *  densest around the silhouette and the roll cage. */
const BODY_COLOR = '#ff7413'
const GLOW_COLOR = '#ff4200'
/** Translucent again, by request. Worth knowing what it costs: with depth
 *  writing off nothing can be depth-rejected, so every triangle of the car is
 *  blended and both faces are drawn — the single most expensive thing on the
 *  page. The accumulation is also the effect: overlapping shells build up, so
 *  the roll cage and silhouette read denser than the flat panels. */
const OPACITY_DARK = 0.12
const OPACITY_LIT = 0.38
const GLOW_MAX = 1.9
/** Unveil: lights come up from below and the scene brightens. */
const UNVEIL_MS = 2600
const UNVEIL_DELAY = 250

const clamp01 = (n: number) => Math.min(Math.max(n, 0), 1)
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)
const lerp = (a: number, b: number, t: number) => a + (b - a) * t

function hasWebGL() {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}

function StudioEnvironment({ phase }: { phase: RefObject<Phase> }) {
  const gl = useThree((s) => s.gl)
  const scene = useThree((s) => s.scene)
  const texture = useMemo(() => {
    try {
      const pmrem = new PMREMGenerator(gl)
      const rt = pmrem.fromScene(new RoomEnvironment(), 0.04)
      pmrem.dispose()
      return rt.texture
    } catch {
      return null
    }
  }, [gl])

  useEffect(() => {
    if (texture) scene.environment = texture
    return () => {
      texture?.dispose()
      scene.environment = null
    }
  }, [texture, scene])

  // The environment is what makes the metal read as metal, so it has to come up
  // with the unveil too — otherwise the "unlit" car still has bright reflections.
  useFrame(() => {
    scene.environmentIntensity = lerp(0.02, 0.16, easeOut(phase.current.unveilT))
  })
  return null
}

type Phase = { introT: number; unveilT: number }

function Buggy({
  progress,
  phase,
  onReady,
}: {
  progress: RefObject<number>
  phase: RefObject<Phase>
  onReady: () => void
}) {
  // Decided once per mount: swapping the URL mid-life would re-suspend and
  // restart the intro.
  const [url] = useState(() => (wantsLight() ? MODEL_LIGHT : MODEL))
  const { scene } = useGLTF(url, '/draco/gltf/')
  const group = useRef<Group>(null)

  // Timestamp of the moment the spin finished; null until it does.
  const driveStart = useRef<number | null>(null)
  /** The exit happens once. Scrolling back up rewinds the wordmark and the
   *  card, but not this: a car that reverses back onto the stage undoes the
   *  departure the visitor just watched. */
  const departed = useRef(false)

  const material = useMemo(
    () =>
      new MeshStandardMaterial({
        color: BODY_COLOR,
        emissive: GLOW_COLOR,
        emissiveIntensity: 0,
        metalness: 0,
        roughness: 0.46,
        transparent: true,
        opacity: OPACITY_DARK,
        depthWrite: false,
        side: DoubleSide,
      }),
    [],
  )

  useEffect(() => {
    scene.traverse((o: Object3D) => {
      const m = o as Mesh
      if (m.isMesh) m.material = material
    })
    return () => material.dispose()
  }, [scene, material])

  const offset = useMemo(() => {
    const box = new Box3().setFromObject(scene)
    const c = box.getCenter(new Vector3())
    return new Vector3(-c.x, -c.y, -c.z)
  }, [scene])

  useEffect(() => () => {
    delete document.documentElement.dataset.carGone
  }, [])

  // Draco decoding takes ~2s after the GLB lands, and this component is
  // suspended for all of it. Signalling here — the first mount after the model
  // resolves — is what lets the unveil start when there is something to
  // unveil, instead of running down while the stage is still empty.
  useEffect(onReady, [onReady])

  useFrame(() => {
    const g = group.current
    if (!g) return
    const introT = phase.current.introT

    // The unveil runs through the body itself: never fully transparent, so the
    // dark glass silhouette is there from the first frame and what comes up is
    // the emission, not the body fading in.
    const u = easeOut(phase.current.unveilT)
    material.opacity = lerp(OPACITY_DARK, OPACITY_LIT, u)
    material.emissiveIntensity = u * GLOW_MAX

    const p = clamp01(progress.current ?? 0)
    const introOffset = (easeOut(introT) - 1) * INTRO_TURNS * Math.PI * 2

    let spin: number
    let dx = 0
    if (!departed.current && p <= SPIN_END) {
      spin = easeOut(p / SPIN_END) * SCROLL_SPIN
    } else {
      spin = SCROLL_SPIN
      if (driveStart.current == null) {
        driveStart.current = performance.now()
        departed.current = true
        // The pool of light under the car is scroll-driven in CSS; this is how
        // it learns the car is not coming back.
        document.documentElement.dataset.carGone = 'true'
      }
      // Time-based, so it drives away by itself once the spin completes.
      const q = clamp01((performance.now() - driveStart.current) / DRIVE_MS)
      dx = EXIT_DIR * q * q * EXIT_DISTANCE
    }

    g.rotation.y = FRONT + introOffset + spin
    g.position.x = dx
  })

  return (
    <group ref={group}>
      <primitive object={scene} position={offset} />
    </group>
  )
}

/**
 * The unveil, done with light instead of paint.
 *
 * A warm point light climbs from below the car while the key and fill come up
 * behind it, so the body genuinely goes from unlit to lit — the geometry is
 * fully opaque the whole time. Darkening it with a black overlay only looked
 * like a fade because a near-black car on a near-black page is indistinguishable
 * from a transparent one.
 */
function UnveilRig({ phase }: { phase: RefObject<Phase> }) {
  const sweep = useRef<PointLight>(null)
  const key = useRef<PointLight>(null)
  const rim = useRef<PointLight>(null)

  useFrame(() => {
    const t = easeOut(phase.current.unveilT)
    if (sweep.current) {
      sweep.current.position.y = lerp(-1.6, 2.0, t)
      // Brightest mid-sweep, then hands off to the key light.
      sweep.current.intensity = 9 * Math.sin(Math.PI * clamp01(t)) + 1
    }
    if (key.current) key.current.intensity = lerp(0, 4.5, clamp01((t - 0.25) / 0.75))
    if (rim.current) rim.current.intensity = lerp(0, 5, clamp01((t - 0.4) / 0.6))
  })

  return (
    <>
      <pointLight ref={sweep} position={[0, -1.6, 2.6]} color="#ff9a40" distance={14} decay={1.4} />
      <pointLight ref={key} position={[3.4, 4.2, 4.5]} color="#ffbe7a" distance={26} decay={1.5} />
      <pointLight ref={rim} position={[-4.2, 2.2, -3.6]} color="#ff8a3d" distance={22} decay={1.5} />
    </>
  )
}

function Scene({ progress }: { progress: RefObject<number> }) {
  const phase = useRef<Phase>({ introT: 0, unveilT: 0 })
  const start = useRef(0)

  // Set when the model is ready, not on mount: starting here would spend the
  // unveil on an empty stage and the car would appear already lit. Not during
  // render either — performance.now() in a render body is impure.
  const onReady = useCallback(() => {
    start.current = performance.now()
  }, [])

  useFrame(() => {
    if (!start.current) return
    const elapsed = performance.now() - start.current
    phase.current.introT = clamp01(elapsed / INTRO_MS)
    phase.current.unveilT = clamp01((elapsed - UNVEIL_DELAY) / UNVEIL_MS)
  })

  return (
    <>
      <StudioEnvironment phase={phase} />
      <UnveilRig phase={phase} />
      <Suspense fallback={null}>
        <Buggy progress={progress} phase={phase} onReady={onReady} />
      </Suspense>
    </>
  )
}

export function HeroCar3D({
  progress,
  subscribe,
}: {
  progress: RefObject<number>
  subscribe: (fn: (p: number) => void) => () => void
}) {
  const [visible, setVisible] = useState(true)
  const [failed, setFailed] = useState(() => !hasWebGL())
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  // If the browser takes the context away — Safari does this under tab
  // pressure — drop to the pre-rendered turntable rather than showing nothing.
  if (failed) return <HeroCarFrames progress={progress} subscribe={subscribe} />

  return (
    <div className="hero-car" ref={wrap} aria-hidden="true">
      {/* dpr caps at 1.5, not 2: on a retina display dpr 2 is four times the
          pixels of dpr 1, and this canvas redraws continuously. */}
      <Canvas
        frameloop={visible ? 'always' : 'never'}
        dpr={[1, wantsLight() ? 1 : 1.5]}
        camera={{ position: [0, 1.05, 6.4], fov: 32 }}
        gl={{ antialias: true, alpha: true }}
        onCreated={({ gl }) => {
          gl.domElement.addEventListener('webglcontextlost', (e) => {
            e.preventDefault()
            setFailed(true)
          })
        }}
      >
        <Scene progress={progress} />
      </Canvas>
    </div>
  )
}

useGLTF.preload(wantsLight() ? MODEL_LIGHT : MODEL, '/draco/gltf/')
