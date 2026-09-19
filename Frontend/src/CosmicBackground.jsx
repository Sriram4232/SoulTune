import { useEffect, useRef } from 'react';

export default function CosmicBackground() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let animId;

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const onResize = () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };

    window.addEventListener('resize', onResize);

    const count = Math.min(80, Math.floor((width * height) / 18000));
    const stars = Array.from({ length: Math.max(45, count) }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      radius: Math.random() * 1.4 + 0.6,
      alpha: Math.random() * 0.7 + 0.25,
      delta: (Math.random() * 0.015 + 0.005) * (Math.random() > 0.5 ? 1 : -1),
      speedY: (Math.random() * 0.25 + 0.06) * -1,
      speedX: (Math.random() * 0.08 - 0.04),
    }));

    function renderParticles() {
      ctx.clearRect(0, 0, width, height);

      for (let i = 0; i < stars.length; i++) {
        const s = stars[i];
        s.alpha += s.delta;
        if (s.alpha > 0.95 || s.alpha < 0.18) s.delta = -s.delta;
        s.y += s.speedY;
        s.x += s.speedX;

        if (s.y < -5) {
          s.y = height + 5;
          s.x = Math.random() * width;
        }
        if (s.x < -5) s.x = width + 5;
        if (s.x > width + 5) s.x = -5;

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(165, 231, 255, ${Math.max(0.05, Math.min(1, s.alpha))})`;
        ctx.shadowBlur = 5;
        ctx.shadowColor = '#00d2ff';
        ctx.fill();
      }

      animId = requestAnimationFrame(renderParticles);
    }

    renderParticles();

    return () => {
      window.removeEventListener('resize', onResize);
      cancelAnimationFrame(animId);
    };
  }, []);

  return (
    <div className="cosmic-bg-layer" aria-hidden="true">
      <div className="cosmic-ambient-glow glow-1" />
      <div className="cosmic-ambient-glow glow-2" />
      <canvas ref={canvasRef} className="cosmic-canvas" />
    </div>
  );
}
