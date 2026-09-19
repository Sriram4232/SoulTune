import { useEffect, useRef } from 'react';
import { AudioLines, ArrowRight, ChevronRight, X, LoaderCircle, AlertCircle, Music2, Sparkles, RotateCw } from 'lucide-react';
import { percent, safeUrl, titleCase } from './api';

export function Brand({ compact = false, onClick }) {
  return <button className="brand ripple-object" onClick={onClick} aria-label="SoulTune home"><span className="brand-mark"><AudioLines size={24} strokeWidth={2.2} /></span>{!compact && <span>soul<span className="brand-light">tune</span><span className="brand-dot">.</span></span>}</button>;
}

export function Artwork({ seed = '', className = '', imageUrl, children }) {
  const index = [...String(seed)].reduce((a, c) => a + c.charCodeAt(0), 0) % 6;
  const url = safeUrl(imageUrl);
  return <div className={`artwork artwork-${index} ${className}`} aria-hidden="true">{url && <img src={url} alt="" loading="lazy" onError={event => { event.currentTarget.hidden = true; }} />}<span className="artwork-orbit orbit-one" /><span className="artwork-orbit orbit-two" /><span className="artwork-grain" />{children}</div>;
}

export function EmptyState({ icon: Icon = Music2, title, description, action, actionLabel = 'Create a playlist' }) {
  return <div className="empty-state ripple-object"><span className="empty-icon"><Icon size={30} /></span><h3 className="ripple-text">{title}</h3><p>{description}</p>{action && <button className="button primary" onClick={action}>{actionLabel}<ArrowRight size={16} /></button>}</div>;
}

export function ErrorBox({ error, retry }) {
  if (!error) return null;
  return <div className="error-box" role="alert"><AlertCircle size={18} /><div>{error.message || String(error)}</div>{retry && <button className="text-button" onClick={retry}><RotateCw size={14} /> Retry</button>}</div>;
}

export function Loading({ text = 'Loading your music…' }) {
  return <div className="loading-state" role="status"><LoaderCircle size={25} className="spin" /><p className="ripple-text">{text}</p></div>;
}

export function SkeletonCards() {
  return <div className="playlist-grid" aria-label="Loading playlists" role="status">{[1, 2, 3].map(i => <div className="skeleton-card" key={i}><div className="skeleton square" /><div className="skeleton line" /><div className="skeleton line short" /></div>)}</div>;
}

export function PageHeading({ eyebrow, title, description, children }) {
  return <header className="page-heading"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1 className="ripple-text">{title}</h1>{description && <p className="page-description">{description}</p>}</div>{children && <div className="page-heading-actions">{children}</div>}</header>;
}

export function SectionHeading({ title, subtitle, action, actionLabel }) {
  return <div className="section-heading"><div><h2 className="ripple-text">{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action && <button className="text-button" onClick={action}>{actionLabel}<ChevronRight size={16} /></button>}</div>;
}

export function Chips({ options, selected, onChange, label }) {
  return <div className="chip-options" role="group" aria-label={label}>{options.map(option => {
    const chosen = (selected || []).some(x => x.toLowerCase() === option.toLowerCase());
    return <button key={option} type="button" className={`chip choice-chip ripple-object ${chosen ? 'selected' : ''}`} aria-pressed={chosen} onClick={() => onChange(chosen ? selected.filter(x => x.toLowerCase() !== option.toLowerCase()) : [...(selected || []), option.toLowerCase()])}>{option}{chosen && <span aria-hidden="true">✓</span>}</button>;
  })}</div>;
}

export function Meter({ label, value, tone = '', detail }) {
  return <div className={`meter ${tone}`}><div className="meter-label"><span>{label}</span><span className="label-numeric">{detail ?? `${percent(value)}%`}</span></div><div className="meter-track"><span style={{ width: `${percent(value)}%` }} /></div></div>;
}

export function PlaylistCard({ playlist, onOpen }) {
  return <button className="playlist-card ripple-object" onClick={() => onOpen(playlist.id)}><Artwork seed={playlist.id || playlist.name}><span className="artwork-caption">{titleCase(playlist.profile?.primary_mood || 'Your sound')}</span><span className="artwork-number">VT / {String((playlist.tracks || []).length).padStart(2, '0')}</span><span className="artwork-play"><ArrowRight size={22} /></span></Artwork><div className="playlist-card-title"><h3 className="ripple-text">{playlist.name}</h3>{playlist.saved && <span className="saved-dot" title="Saved" />}</div><p>{playlist.tracks?.length || 0} tracks <span>·</span> {titleCase(playlist.profile?.activity || playlist.profile?.primary_mood || 'Personal mix')}</p></button>;
}

export function ConfirmDialog({ open, title, description, confirmLabel = 'Confirm', danger = false, onClose, onConfirm, children, busy }) {
  const ref = useRef(null);
  useEffect(() => { if (open && !ref.current.open) ref.current.showModal(); else if (!open && ref.current.open) ref.current.close(); }, [open]);
  return <dialog ref={ref} className="modal" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === ref.current) onClose(); }}><div className="modal-content"><button className="icon-button modal-close" aria-label="Close dialog" onClick={onClose}><X size={20} /></button><h2>{title}</h2><p>{description}</p>{children}<div className="modal-actions"><button className="button secondary" disabled={busy} onClick={onClose}>Cancel</button><button className={`button ${danger ? 'danger' : 'primary'}`} disabled={busy} onClick={onConfirm}>{busy && <LoaderCircle size={16} className="spin" />}{confirmLabel}</button></div></div></dialog>;
}

export function StatusPill({ health }) {
  const local = !health?.music_api_configured;
  return <span className="status-pill"><span className={`status-dot ${local ? 'local' : ''}`} />{health ? local ? 'Local discovery mode' : 'Ready to discover' : 'Connecting'}</span>;
}

export function CuratorBadge() { return <span className="curator-badge"><Sparkles size={13} /> MADE FOR YOUR MOMENT</span>; }
