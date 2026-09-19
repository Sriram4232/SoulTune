import { useEffect, useRef } from 'react';

export default function LiquidCursor() {
  const canvasRef = useRef(null);
  const cursorRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const cursor = cursorRef.current;
    if (!canvas || !cursor) return;

    const ctx = canvas.getContext('2d');
    let animId;
    let visualRipples = [];
    let textItems = [];
    let objectItems = [];

    let mouseX = -1000;
    let mouseY = -1000;
    let targetMouseX = -1000;
    let targetMouseY = -1000;
    let lastMoveTime = 0;
    let isCursorVisible = false;

    function resizeCanvas() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      cacheGeometry();
    }

    function splitText(element) {
      if (element.dataset.rippleSplit === 'true') return;
      element.dataset.rippleSplit = 'true';

      if (element.children.length === 0 && element.textContent) {
        const text = element.textContent;
        const frag = document.createDocumentFragment();
        for (let i = 0; i < text.length; i++) {
          const span = document.createElement('span');
          span.className = 'ripple-char';
          span.textContent = text[i];
          frag.appendChild(span);
        }
        element.textContent = '';
        element.appendChild(frag);
      } else {
        Array.from(element.childNodes).forEach(node => {
          if (node.nodeType === Node.TEXT_NODE && node.nodeValue && node.nodeValue.trim().length > 0) {
            const text = node.nodeValue;
            const spanWrap = document.createElement('span');
            spanWrap.style.display = 'inline';
            for (let i = 0; i < text.length; i++) {
              const span = document.createElement('span');
              span.className = 'ripple-char';
              span.textContent = text[i];
              spanWrap.appendChild(span);
            }
            node.replaceWith(spanWrap);
          } else if (node.nodeType === Node.ELEMENT_NODE && !node.classList.contains('ripple-char')) {
            splitText(node);
          }
        });
      }
    }

    function prepareTextElements() {
      const rippleTexts = document.querySelectorAll('.ripple-text');
      rippleTexts.forEach(el => splitText(el));
    }

    function cacheGeometry() {
      prepareTextElements();

      textItems = [];
      const charElements = document.querySelectorAll('.ripple-char');
      charElements.forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          textItems.push({
            el,
            cx: rect.left + rect.width / 2,
            cy: rect.top + rect.height / 2,
            currDx: 0,
            currDy: 0,
            targetDx: 0,
            targetDy: 0,
            vx: 0,
            vy: 0,
            scale: 1,
            targetScale: 1
          });
        }
      });

      objectItems = [];
      const objElements = document.querySelectorAll('.ripple-object');
      objElements.forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          objectItems.push({
            el,
            cx: rect.left + rect.width / 2,
            cy: rect.top + rect.height / 2,
            currDx: 0,
            currDy: 0,
            targetDx: 0,
            targetDy: 0,
            vx: 0,
            vy: 0,
            scale: 1,
            targetScale: 1
          });
        }
      });
    }

    class Ripple {
      constructor(x, y, maxRadius, maxSpeed, strength, causesDisplacement, color, strokeWidth) {
        this.x = x;
        this.y = y;
        this.radius = 0;
        this.maxRadius = maxRadius || 340;
        this.speed = maxSpeed || 4.5;
        this.strength = strength || 1.0;
        this.causesDisplacement = causesDisplacement || false;
        this.color = color || 'rgba(0, 210, 255, ';
        this.strokeWidth = strokeWidth || 2.4;
        this.alive = true;
        this.age = 0;
        this.maxAge = 64;
      }

      update() {
        this.radius += this.speed;
        this.age++;
        if (this.radius > this.maxRadius || this.age > this.maxAge) {
          this.alive = false;
        }
      }

      draw(c) {
        const progress = this.age / this.maxAge;
        const baseAlpha = this.causesDisplacement ? 0.65 : 0.28;
        const alpha = Math.max(0, (1 - progress) * baseAlpha * this.strength);

        c.save();
        c.beginPath();
        c.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
        c.lineWidth = Math.max(0.8, this.strokeWidth * (1 - progress * 0.7));
        c.strokeStyle = `${this.color}${alpha})`;
        if (this.causesDisplacement) {
          c.shadowColor = '#00d2ff';
          c.shadowBlur = 14 * (1 - progress);
        } else {
          c.shadowColor = '#47d6ff';
          c.shadowBlur = 6 * (1 - progress);
        }
        c.stroke();
        c.restore();
      }
    }

    const onMouseMove = e => {
      targetMouseX = e.clientX;
      targetMouseY = e.clientY;

      if (!isCursorVisible) {
        isCursorVisible = true;
        cursor.style.opacity = '1';
      }

      // Check if hovering an interactive target to style water droplet
      const targetElem = e.target;
      if (
        targetElem &&
        (targetElem.closest(
          'button, a, input, textarea, select, [role="button"], .group, .vibe-card, .playlist-card, .example-card, .choice-chip, .chip, .interactive'
        ) ||
          targetElem.classList.contains('ripple-char'))
      ) {
        cursor.classList.add('hovering-interactive');
      } else {
        cursor.classList.remove('hovering-interactive');
      }

      // MOVEMENT RIPPLE (Visual ONLY on canvas, causesDisplacement = false)
      const now = performance.now();
      if (now - lastMoveTime > 48) {
        visualRipples.push(
          new Ripple(targetMouseX, targetMouseY, 110, 2.8, 0.55, false, 'rgba(0, 210, 255, ', 1.8)
        );
        lastMoveTime = now;
      }
    };

    const onPointerDown = e => {
      cursor.classList.add('clicking');

      // Re-cache geometry in case layout or scroll position changed
      cacheGeometry();

      // Multi-Ring Fluid Click: Physical Waves through letters, cards, and buttons
      // Ring 1: Primary explosive water wavefront
      visualRipples.push(
        new Ripple(e.clientX, e.clientY, 380, 5.2, 1.25, true, 'rgba(165, 231, 255, ', 3.2)
      );

      // Ring 2: Secondary harmonic ring (delayed)
      setTimeout(() => {
        visualRipples.push(
          new Ripple(e.clientX, e.clientY, 300, 4.4, 0.85, true, 'rgba(0, 210, 255, ', 2.4)
        );
      }, 70);

      // Ring 3: Tertiary echo ring
      setTimeout(() => {
        visualRipples.push(
          new Ripple(e.clientX, e.clientY, 220, 3.6, 0.6, true, 'rgba(192, 193, 255, ', 1.8)
        );
      }, 140);
    };

    const onPointerUp = () => {
      cursor.classList.remove('clicking');
    };

    const onMouseLeave = () => {
      isCursorVisible = false;
      cursor.style.opacity = '0';
    };

    const onMouseEnter = () => {
      isCursorVisible = true;
      cursor.style.opacity = '1';
    };

    window.addEventListener('mousemove', onMouseMove, { passive: true });
    window.addEventListener('pointerdown', onPointerDown, { passive: true });
    window.addEventListener('pointerup', onPointerUp, { passive: true });
    document.addEventListener('mouseleave', onMouseLeave);
    document.addEventListener('mouseenter', onMouseEnter);
    window.addEventListener('resize', resizeCanvas);
    window.addEventListener('scroll', cacheGeometry, { passive: true });

    // MutationObserver to automatically re-cache geometry when routes or components change
    const observer = new MutationObserver(() => {
      cacheGeometry();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    resizeCanvas();

    // Physics Engine constants:
    const STIFFNESS = 92;
    const DAMPING = 16;
    const DT = 0.016;

    function applyPhysics() {
      // Smooth liquid cursor interpolation
      if (mouseX < -500) {
        mouseX = targetMouseX;
        mouseY = targetMouseY;
      } else {
        mouseX += (targetMouseX - mouseX) * 0.32;
        mouseY += (targetMouseY - mouseY) * 0.32;
      }

      if (mouseX > -500) {
        cursor.style.left = `${mouseX}px`;
        cursor.style.top = `${mouseY}px`;
      }

      // Reset target displacements
      textItems.forEach(item => {
        item.targetDx = 0;
        item.targetDy = 0;
        item.targetScale = 1;
      });
      objectItems.forEach(item => {
        item.targetDx = 0;
        item.targetDy = 0;
        item.targetScale = 1;
      });

      // ONLY Click Waves with causesDisplacement = true apply physical displacement to page content!
      // (Hover/mousemove does NOT displace page content, fulfilling the user's explicit requirement).
      visualRipples.forEach(r => {
        if (!r.causesDisplacement) return;

        // Wave across letters
        textItems.forEach(item => {
          const dx = item.cx - r.x;
          const dy = item.cy - r.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const waveDelta = Math.abs(dist - r.radius);
          if (waveDelta < 48 && dist > 0) {
            const factor = (1 - waveDelta / 48) * (1 - r.age / r.maxAge) * r.strength;
            const push = factor * 11.5;
            item.targetDx += (dx / dist) * push;
            item.targetDy += (dy / dist) * push;
            item.targetScale = Math.max(item.targetScale, 1 + factor * 0.08);
          }
        });

        // Wave across cards and buttons
        objectItems.forEach(item => {
          const dx = item.cx - r.x;
          const dy = item.cy - r.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const waveDelta = Math.abs(dist - r.radius);
          if (waveDelta < 56 && dist > 0) {
            const factor = (1 - waveDelta / 56) * (1 - r.age / r.maxAge) * r.strength;
            const push = factor * 6.5;
            item.targetDx += (dx / dist) * push;
            item.targetDy += (dy / dist) * push;
            item.targetScale = Math.max(item.targetScale, 1 + factor * 0.02);
          }
        });
      });

      // Spring physics integration for text
      textItems.forEach(item => {
        const ax = -STIFFNESS * (item.currDx - item.targetDx) - DAMPING * item.vx;
        const ay = -STIFFNESS * (item.currDy - item.targetDy) - DAMPING * item.vy;
        item.vx += ax * DT;
        item.vy += ay * DT;
        item.currDx += item.vx * DT;
        item.currDy += item.vy * DT;
        item.scale += (item.targetScale - item.scale) * 0.18;

        if (
          Math.abs(item.currDx) > 0.03 ||
          Math.abs(item.currDy) > 0.03 ||
          Math.abs(item.scale - 1) > 0.003
        ) {
          item.el.style.transform = `translate3d(${item.currDx.toFixed(2)}px, ${item.currDy.toFixed(2)}px, 0) scale(${item.scale.toFixed(3)})`;
        } else if (item.el.style.transform) {
          item.el.style.transform = '';
          item.currDx = 0;
          item.currDy = 0;
          item.vx = 0;
          item.vy = 0;
          item.scale = 1;
        }
      });

      // Spring physics integration for interactive objects
      objectItems.forEach(item => {
        const ax = -STIFFNESS * (item.currDx - item.targetDx) - DAMPING * item.vx;
        const ay = -STIFFNESS * (item.currDy - item.targetDy) - DAMPING * item.vy;
        item.vx += ax * DT;
        item.vy += ay * DT;
        item.currDx += item.vx * DT;
        item.currDy += item.vy * DT;
        item.scale += (item.targetScale - item.scale) * 0.14;

        if (
          Math.abs(item.currDx) > 0.03 ||
          Math.abs(item.currDy) > 0.03 ||
          Math.abs(item.scale - 1) > 0.003
        ) {
          item.el.style.transform = `translate3d(${item.currDx.toFixed(2)}px, ${item.currDy.toFixed(2)}px, 0) scale(${item.scale.toFixed(3)})`;
        } else if (item.el.style.transform) {
          item.el.style.transform = '';
          item.currDx = 0;
          item.currDy = 0;
          item.vx = 0;
          item.vy = 0;
          item.scale = 1;
        }
      });
    }

    function renderLoop() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (let i = visualRipples.length - 1; i >= 0; i--) {
        const r = visualRipples[i];
        r.update();
        if (r.alive) {
          r.draw(ctx);
        } else {
          visualRipples.splice(i, 1);
        }
      }

      applyPhysics();
      animId = requestAnimationFrame(renderLoop);
    }

    renderLoop();

    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointerup', onPointerUp);
      document.removeEventListener('mouseleave', onMouseLeave);
      document.removeEventListener('mouseenter', onMouseEnter);
      window.removeEventListener('resize', resizeCanvas);
      window.removeEventListener('scroll', cacheGeometry);
      observer.disconnect();
      cancelAnimationFrame(animId);
    };
  }, []);

  return (
    <>
      <canvas id="rippleCanvas" ref={canvasRef} />
      <div id="waterCursor" ref={cursorRef} className="water-cursor">
        <span className="water-cursor-dot" />
      </div>
    </>
  );
}
