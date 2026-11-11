import { useEffect, useRef } from 'react'

type Particle = {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
}

type Shape = {
  x: number
  y: number
  size: number
  rotation: number
  rotationSpeed: number
  vx: number
  vy: number
  kind: 'circle' | 'triangle' | 'square'
  alpha: number
}

function createParticles(width: number, height: number): Particle[] {
  const count = Math.min(78, Math.max(28, Math.floor((width * height) / 18_000)))
  return Array.from({ length: count }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    vx: (Math.random() - 0.5) * 0.28,
    vy: (Math.random() - 0.5) * 0.28,
    radius: Math.random() * 1.6 + 0.7,
  }))
}

function createShapes(width: number, height: number): Shape[] {
  const kinds: Shape['kind'][] = ['circle', 'triangle', 'square']
  return Array.from({ length: 8 }, (_, index) => ({
    x: Math.random() * width,
    y: Math.random() * height,
    size: 18 + Math.random() * 42,
    rotation: Math.random() * Math.PI * 2,
    rotationSpeed: (Math.random() - 0.5) * 0.004,
    vx: (Math.random() - 0.5) * 0.18,
    vy: (Math.random() - 0.5) * 0.18,
    kind: kinds[index % kinds.length],
    alpha: 0.08 + Math.random() * 0.1,
  }))
}

function drawShape(ctx: CanvasRenderingContext2D, shape: Shape, stroke: string) {
  ctx.save()
  ctx.translate(shape.x, shape.y)
  ctx.rotate(shape.rotation)
  ctx.strokeStyle = stroke
  ctx.lineWidth = 1
  const half = shape.size / 2

  if (shape.kind === 'circle') {
    ctx.beginPath()
    ctx.arc(0, 0, half, 0, Math.PI * 2)
    ctx.stroke()
  } else if (shape.kind === 'square') {
    ctx.strokeRect(-half, -half, shape.size, shape.size)
  } else {
    ctx.beginPath()
    ctx.moveTo(0, -half)
    ctx.lineTo(half, half)
    ctx.lineTo(-half, half)
    ctx.closePath()
    ctx.stroke()
  }
  ctx.restore()
}

export function HeroBackdrop() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    let width = 0
    let height = 0
    let particles: Particle[] = []
    let shapes: Shape[] = []
    let frame = 0
    let dpr = 1

    const isDark = () => document.documentElement.classList.contains('dark')

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      width = rect.width
      height = rect.height
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      particles = createParticles(width, height)
      shapes = createShapes(width, height)
      render(0)
    }

    const render = (time: number) => {
      const dark = isDark()
      const particleColor = dark ? '210, 238, 220' : '32, 84, 62'
      const lineColor = dark ? '180, 225, 198' : '36, 92, 66'
      ctx.clearRect(0, 0, width, height)

      if (!reducedMotion.matches && time > 0) {
        for (const p of particles) {
          p.x += p.vx
          p.y += p.vy
          if (p.x < 0 || p.x > width) p.vx *= -1
          if (p.y < 0 || p.y > height) p.vy *= -1
        }
        for (const shape of shapes) {
          shape.x += shape.vx
          shape.y += shape.vy
          shape.rotation += shape.rotationSpeed
          if (shape.x < -shape.size || shape.x > width + shape.size) shape.vx *= -1
          if (shape.y < -shape.size || shape.y > height + shape.size) shape.vy *= -1
        }
      }

      for (let i = 0; i < particles.length; i += 1) {
        for (let j = i + 1; j < particles.length; j += 1) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          const distance = Math.hypot(dx, dy)
          if (distance < 112) {
            ctx.strokeStyle = `rgba(${lineColor}, ${0.12 * (1 - distance / 112)})`
            ctx.beginPath()
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            ctx.stroke()
          }
        }
      }

      for (const shape of shapes) {
        drawShape(ctx, shape, `rgba(${lineColor}, ${shape.alpha})`)
      }

      for (const p of particles) {
        ctx.fillStyle = `rgba(${particleColor}, 0.42)`
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    const animate = (time: number) => {
      render(time)
      if (!reducedMotion.matches) frame = requestAnimationFrame(animate)
    }

    const rerun = () => {
      cancelAnimationFrame(frame)
      if (reducedMotion.matches) render(0)
      else frame = requestAnimationFrame(animate)
    }

    resize()
    frame = requestAnimationFrame(animate)
    reducedMotion.addEventListener('change', rerun)
    window.addEventListener('resize', resize)
    return () => {
      cancelAnimationFrame(frame)
      reducedMotion.removeEventListener('change', rerun)
      window.removeEventListener('resize', resize)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  )
}
