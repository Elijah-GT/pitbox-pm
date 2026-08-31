import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { Suspense, useEffect, useLayoutEffect, useMemo, useRef, type RefObject } from 'react'
import {
  Box3,
  Group,
  Mesh,
  MeshStandardMaterial,
  PMREMGenerator,
  Vector3,
  type Object3D,
} from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'

const MODEL = '/models/buggy-hero.glb'
/** Where the car faces at rest, before any scrolling. Three-quarter view. */
const START_Y = -0.55

/**
 * The STEP export carries no colours and no usable part names (SolidWorks
 * writes NAUO1..N for assembly occurrences), so there is nothing to key
 * per-part materials off. One brushed metal for the whole car is the honest
 * choice, and it deliberately matches the silver of the hero wordmark.
 */
function useCarMaterial() {
  return useMemo(
    () =>
      new MeshStandardMaterial({
        color: '#9aa3b2',
        metalness: 0.92,
        roughness: 0.36,
        envMapIntensity: 1.15,
      }),
    [],
  )
}

/** Studio reflections generated on the GPU — no HDRI to download. Attached
    declaratively rather than by assigning scene.environment, so React owns the
    lifetime of the render target. */
function StudioEnvironment() {
  const gl = useThree((s) => s.gl)
  const texture = useMemo(() => {
    try {
      const pmrem = new PMREMGenerator(gl)
      const rt = pmrem.fromScene(new RoomEnvironment(), 0.04)
      pmrem.dispose() // the generator goes; its output texture stays valid
      return rt.texture
    } catch (err) {
      console.warn('[HeroCar] environment map unavailable, using lights only', err)
      return null
    }
  }, [gl])

  useEffect(() => () => texture?.dispose(), [texture])

  if (!texture) return null
  return <primitive attach="environment" object={texture} />
}

function Buggy({ progress, spin }: { progress: RefObject<number>; spin: boolean }) {
  const { scene } = useGLTF(MODEL, '/draco/gltf/')
  const group = useRef<Group>(null)
  const material = useCarMaterial()

  useLayoutEffect(() => {
    scene.traverse((o: Object3D) => {
      const mesh = o as Mesh
      if (mesh.isMesh) mesh.material = material
    })
  }, [scene, material])

  // The GLB origin is wherever SolidWorks put it. Offset the model so the group
  // spins about the car's own centre rather than swinging around a far corner.
  const offset = useMemo(() => {
    const box = new Box3().setFromObject(scene)
    const c = box.getCenter(new Vector3())
    return new Vector3(-c.x, -c.y, -c.z)
  }, [scene])

  useFrame(() => {
    if (!group.current) return
    group.current.rotation.y = START_Y + (spin ? progress.current * Math.PI * 2 : 0)
  })

  return (
    <group ref={group}>
      <primitive object={scene} position={offset} />
    </group>
  )
}

/**
 * Renders on demand, not continuously: the car's only input is scroll
 * position, so a frame is drawn when the page scrolls and at no other time.
 * A landing page has no business holding the GPU at 60fps while the visitor
 * reads.
 */
function RedrawOnScroll() {
  const invalidate = useThree((s) => s.invalidate)
  useEffect(() => {
    const onScroll = () => invalidate()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [invalidate])
  return null
}

export function HeroCar({ progress }: { progress: RefObject<number> }) {
  const spin = !window.matchMedia('(prefers-reduced-motion: reduce)').matches

  return (
    <div className="hero-car" aria-hidden="true">
      <Canvas
        frameloop="demand"
        dpr={[1, 2]}
        camera={{ position: [0, 1.15, 6.6], fov: 32 }}
        fallback={<div className="hero-car-fallback" />}
        onCreated={({ gl }) => {
          console.info('[HeroCar] WebGL context created')
          gl.domElement.addEventListener('webglcontextlost', (e) => {
            e.preventDefault()
            console.warn('[HeroCar] WebGL context lost')
          })
        }}
        gl={{ antialias: true, alpha: true }}
      >
        <StudioEnvironment />
        <RedrawOnScroll />
        <hemisphereLight args={['#cfd6e2', '#0e0f12', 0.4]} />
        <directionalLight position={[4, 6, 3]} intensity={1.6} color="#fff3e6" />
        {/* Brand-orange rim from behind, so the silhouette separates from a
            near-black page instead of dissolving into it. */}
        <directionalLight position={[-5, 2.5, -4]} intensity={1.1} color="#ff8a3d" />
        <Suspense fallback={null}>
          <Buggy progress={progress} spin={spin} />
        </Suspense>
      </Canvas>
    </div>
  )
}

useGLTF.preload(MODEL, '/draco/gltf/')
