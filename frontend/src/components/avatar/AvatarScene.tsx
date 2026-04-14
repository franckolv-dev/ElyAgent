"use client";
// -----------------------------------------------------------------------------
// Copyright (c) 2024 Franck OLLIVIER
// Tous droits réservés.
//
// Ce logiciel est mis à disposition sous les termes de la licence
// PolyForm Strict License 1.0.0.
//
// RÉSUMÉ DES CONDITIONS :
// - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
// - INTERDIT : Toute utilisation commerciale sans accord préalable.
// - INTERDIT : Redistribution de versions modifiées de ce code.
//
// Pour consulter le texte intégral de la licence, veuillez vous référer au
// fichier LICENSE à la racine du projet ou visiter :
// https://polyformproject.org/licenses/strict/1.0.0/
// -----------------------------------------------------------------------------

import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import { useRef, useMemo, useState, useEffect, Component, type ReactNode, type ErrorInfo } from "react";
import * as THREE from "three";
import type { AvatarState } from "./CyberpunkAvatar";

// ─── State → RGB ───────────────────────────────────────────────────────────
const COLORS: Record<AvatarState, [number, number, number]> = {
  idle:      [0.0,  0.82, 1.0 ],
  thinking:  [0.67, 0.0,  1.0 ],
  speaking:  [0.0,  1.0,  0.35],
  alert:     [1.0,  0.12, 0.22],
  listening: [1.0,  0.82, 0.0 ],
};

// ─── Vertex shader ─────────────────────────────────────────────────────────
const VERT = /* glsl */ `
  uniform float uTime;
  uniform float uGlitch;

  varying vec3  vPos;
  varying vec3  vNorm;
  varying vec3  vWorldPos;
  varying float vOrigY;   // undisplaced Y, passed to fragment for lip-line

  float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
  }

  void main() {
    vec3 pos = position;
    vec3 n   = normal;

    vOrigY = position.y;  // store undisplaced Y before any animation

    // Breathing
    pos += n * sin(uTime * 0.7) * 0.003;

    // Glitch (alert)
    if (uGlitch > 0.5) {
      float g = hash21(vec2(floor(pos.y * 25.0), floor(uTime * 5.0)));
      pos.x += (g - 0.5) * 0.035;
      pos.z += (hash21(vec2(floor(pos.x * 20.0), uTime * 3.0)) - 0.5) * 0.025;
    }

    vPos      = pos;
    vNorm     = normalize(normalMatrix * n);
    vWorldPos = (modelMatrix * vec4(pos, 1.0)).xyz;

    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`;

// ─── Fragment shader: projected grid + fresnel + lip line ──────────────────
const FRAG = /* glsl */ `
  #define PI 3.14159265359

  uniform vec3  uColor;
  uniform float uTime;
  uniform float uPulse;
  uniform float uSpeaking;  // 1.0 when speaking, else 0.0

  varying vec3  vPos;
  varying vec3  vNorm;
  varying vec3  vWorldPos;
  varying float vOrigY;   // undisplaced Y for lip-line detection

  void main() {
    // ── Fresnel ──
    vec3 viewDir = normalize(cameraPosition - vWorldPos);
    float fresnel = 1.0 - abs(dot(normalize(vNorm), viewDir));
    fresnel = pow(fresnel, 2.2);

    // ── Spherical UV projection for grid ──
    float u = atan(vPos.x, vPos.z) / (2.0 * PI) + 0.5;
    float v = (vPos.y + 1.0) * 0.5;

    float hRaw  = abs(fract(v * 18.0) - 0.5);
    float hLine = 1.0 - smoothstep(0.0, 0.035, hRaw);
    float vRaw  = abs(fract(u * 14.0) - 0.5);
    float vLine = 1.0 - smoothstep(0.0, 0.040, vRaw);
    float grid  = max(hLine, vLine);
    float node  = (1.0 - smoothstep(0.0, 0.08, hRaw)) * (1.0 - smoothstep(0.0, 0.10, vRaw));

    // ── Scan band ──
    float scan = 1.0 - smoothstep(0.0, 0.06, abs(v - fract(uTime * 0.08)));

    // ── Compose base ──
    float alpha = grid * 0.55 + node * 0.45 + fresnel * 0.35 + scan * 0.18 + 0.015;
    alpha      *= uPulse;
    alpha       = clamp(alpha, 0.0, 1.0);
    vec3 col    = uColor * (1.0 + grid * 0.2 + node * 0.4 + fresnel * 0.3);

    // ── Lip sync: boost the mouth grid-line segment intermittently ──
    // The 2nd horizontal grid line from the chin sits at y ≈ -0.50
    // (grid lines live at fract(v*18)=0.5, v=(y+1)/2 → k=4 gives y=-0.5)
    if (uSpeaking > 0.5) {
      // Use the ORIGINAL (undisplaced) Y so the jaw animation doesn't push
      // vertices out of the target zone when blink peaks at the same phase
      float vFrag  = (vOrigY + 1.0) * 0.5;
      float hMouth = abs(fract(vFrag * 18.0) - 0.5);
      // 2× wider than regular grid lines so the boost is clearly visible
      float onLine = 1.0 - smoothstep(0.0, 0.08, hMouth);

      // k=8 → y = 2*(8.5/18)-1 ≈ -0.056
      float yZone  = 1.0 - smoothstep(0.0, 0.06, abs(vOrigY - (-0.056)));

      // Between the two vertical lines that flank the nose (~nose width)
      float xMask  = 1.0 - smoothstep(0.09, 0.16, abs(vPos.x));
      float zMask  = smoothstep(0.06, 0.20, vPos.z);

      // Random fast blink: 14 slots/s, each slot independently on/off
      float slot   = floor(uTime * 8.0);
      float rnd    = fract(sin(slot * 78.233 + 1.7) * 43758.5453);
      float decay  = 1.0 - smoothstep(0.0, 0.55, fract(uTime * 8.0));
      float blink  = 0.3 + 0.7 * step(0.3, rnd) * decay;

      float lipGlow = onLine * yZone * xMask * zMask * blink;

      // Strong colour boost so the segment clearly stands out vs neighbours
      alpha = max(alpha, lipGlow * 0.98);
      col   = mix(col, uColor * 6.0, lipGlow * 0.95);
    }

    gl_FragColor = vec4(col, alpha);
  }
`;

// ─── Reusable temp ─────────────────────────────────────────────────────────
const _target = new THREE.Color();

// ─── Face model ────────────────────────────────────────────────────────────
function FaceModel({ state }: { state: AvatarState }) {
  const gltf     = useGLTF("/models/avatar.glb");
  const groupRef = useRef<THREE.Group>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const { geometry, material } = useMemo(() => {
    let geo: THREE.BufferGeometry | null = null;
    gltf.scene.traverse((child) => {
      if (!geo && (child as THREE.Mesh).isMesh) {
        geo = (child as THREE.Mesh).geometry.clone();
      }
    });
    if (!geo) throw new Error("No mesh found in avatar GLB");
    // TypeScript cannot track mutations inside traverse's callback, so it
    // narrows `geo` to `never` after the null-check.  Cast it back.
    const safeGeo = geo as THREE.BufferGeometry;

    safeGeo.computeVertexNormals();
    safeGeo.computeBoundingBox();
    const center = safeGeo.boundingBox!.getCenter(new THREE.Vector3());
    safeGeo.translate(-center.x, -center.y, -center.z);

    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uColor:   { value: new THREE.Color(...COLORS.idle) },
        uTime:    { value: 0 },
        uGlitch:  { value: 0 },
        uPulse:    { value: 1.0 },
        uSpeaking: { value: 0.0 },
      },
      vertexShader:   VERT,
      fragmentShader: FRAG,
      transparent:    true,
      depthWrite:     false,
      side:           THREE.DoubleSide,
    });

    return { geometry: safeGeo, material: mat };
  }, [gltf.scene]);

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    const s = stateRef.current;
    const [r, g, b] = COLORS[s];
    _target.setRGB(r, g, b);

    const u = material.uniforms;
    (u.uColor.value as THREE.Color).lerp(_target, 0.08);
    u.uTime.value    = t;
    u.uSpeaking.value = s === "speaking" ? 1.0 : 0.0;
    u.uGlitch.value  = s === "alert" && Math.random() < 0.13 ? 1 : 0;

    // Pulse: alert throbs, listening breathes faster
    if (s === "alert") {
      u.uPulse.value = 0.7 + 0.3 * Math.abs(Math.sin(t * 4));
    } else if (s === "listening") {
      u.uPulse.value = 0.85 + 0.15 * Math.sin(t * 3);
    } else {
      u.uPulse.value += (1.0 - u.uPulse.value) * 0.05;
    }

    if (groupRef.current) {
      // Thinking: gentle head sway
      const yTarget = s === "thinking" ? Math.sin(t * 0.5) * 0.12 : 0;
      groupRef.current.rotation.y += (yTarget - groupRef.current.rotation.y) * 0.04;
      // (breathing bob removed — was causing visible vertical drift)
    }
  });

  return (
    <group ref={groupRef}>
      <mesh geometry={geometry} material={material} />
    </group>
  );
}

// ─── Error boundary: catches EffectComposer / WebGL context-lost crashes ────
interface EBProps { children: ReactNode; fallback: ReactNode }
interface EBState { crashed: boolean }
class WebGLErrorBoundary extends Component<EBProps, EBState> {
  state: EBState = { crashed: false };
  static getDerivedStateFromError(): EBState { return { crashed: true }; }
  componentDidCatch(err: Error, info: ErrorInfo) {
    // Log but don't rethrow — gracefully degrade to fallback avatar
    console.warn("[AvatarScene] WebGL error caught, switching to fallback:", err.message, info.componentStack);
  }
  render() {
    return this.state.crashed ? this.props.fallback : this.props.children;
  }
}

// ─── WebGL availability check ───────────────────────────────────────────────
function isWebGLAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
    );
  } catch {
    return false;
  }
}

// ─── CSS fallback when WebGL is unavailable ─────────────────────────────────
function AvatarFallback({ state }: { state: AvatarState }) {
  const COLORS: Record<string, string> = {
    idle: "#00d2ff", thinking: "#aa00ff", speaking: "#00ff5a",
    alert: "#ff1e37", listening: "#ffd200",
  };
  const color = COLORS[state] ?? "#00d2ff";
  return (
    <div className="w-full h-full flex flex-col items-center justify-center bg-[#060c16]">
      <div className="relative w-28 h-28 mb-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="absolute inset-0 rounded-full border animate-pulse"
            style={{
              borderColor: `${color}${["88", "66", "44", "22"][i]}`,
              transform: `scale(${1 - i * 0.18})`,
              animationDelay: `${i * 0.35}s`,
            }}
          />
        ))}
        <div className="absolute inset-0 flex items-center justify-center text-sm font-mono font-bold" style={{ color }}>
          ELY
        </div>
      </div>
      <p className="text-[9px] font-mono opacity-40" style={{ color }}>WebGL indisponible</p>
    </div>
  );
}

// ─── PostFX — monté seulement après le premier frame du renderer ───────────
function DeferredPostFX() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    // Délai d'un tick pour s'assurer que le renderer WebGL est pleinement initialisé
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);
  if (!ready) return null;
  return (
    <EffectComposer>
      <Bloom
        luminanceThreshold={0.15}
        luminanceSmoothing={0.9}
        intensity={1.2}
        mipmapBlur
      />
    </EffectComposer>
  );
}

// ─── Scene wrapper ─────────────────────────────────────────────────────────
export function AvatarScene({ state }: { state: AvatarState }) {
  const [failed, setFailed] = useState(false);

  // Check WebGL availability before even mounting Canvas
  const webglOk = typeof window !== "undefined" && isWebGLAvailable();

  const fallback = <AvatarFallback state={state} />;

  if (!webglOk || failed) {
    return fallback;
  }

  return (
    <WebGLErrorBoundary fallback={fallback}>
      <Canvas
        camera={{ position: [0, -0.18, 3.1], fov: 38 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        style={{ background: "#060c16" }}
        onCreated={({ scene, gl }) => {
          scene.background = new THREE.Color("#060c16");
          // Handle GPU context loss: switch to CSS fallback instead of crashing
          gl.domElement.addEventListener("webglcontextlost", (e) => {
            e.preventDefault();
            setFailed(true);
          });
        }}
        onError={() => setFailed(true)}
        dpr={[1, 1.5]}
      >
        <FaceModel state={state} />
        <DeferredPostFX />
      </Canvas>
    </WebGLErrorBoundary>
  );
}

useGLTF.preload("/models/avatar.glb");
