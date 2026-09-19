import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Heart, ListPlus } from 'lucide-react';
import { api } from './api';
import { ConfirmDialog, ErrorBox } from './components';

export function PlaylistDialog({ open, onClose, onCreated, track, sourceId, notify }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ['playlists'], queryFn: () => api('/playlists'), enabled: open });
  const [name, setName] = useState(''); const [target, setTarget] = useState('new');
  const [busy, setBusy] = useState(false); const [error, setError] = useState(null); const lock = useRef(false);
  async function save() {
    if (lock.current) return;
    if (target === 'new' && !name.trim()) { setError(new Error('Give your playlist a name.')); return; }
    lock.current = true; setBusy(true); setError(null);
    try {
      let playlist = (query.data?.playlists || []).find(item => item.id === target);
      if (target === 'new') {
        playlist = await api('/playlists', { method: 'POST', body: { name: name.trim() } });
        setTarget(playlist.id); client.setQueryData(['playlist', playlist.id], playlist);
        await client.invalidateQueries({ queryKey: ['playlists'] });
      }
      if (!playlist) throw new Error('Choose an available playlist.');
      if (track) playlist = await api(`/playlists/${playlist.id}/tracks`, { method: 'POST', body: { track_id: track.id, source_id: sourceId, revision: playlist.revision } });
      client.setQueryData(['playlist', playlist.id], playlist);
      await client.invalidateQueries({ queryKey: ['playlists'] });
      notify?.(track ? `Added to ${playlist.name}.` : 'Your empty playlist is ready. Add the songs you want.');
      onCreated?.(playlist); onClose(); setName(''); setTarget('new');
    } catch (e) { setError(e); client.invalidateQueries({ queryKey: ['playlists'] }); }
    finally { lock.current = false; setBusy(false); }
  }
  return <ConfirmDialog open={open} title={track ? 'Keep this song.' : 'Create your playlist.'} description={track ? `${track.title} · ${track.artist}` : 'Give it a name, then add songs from your mood queue, saved songs, or local library.'} confirmLabel={track ? 'Add song' : 'Create playlist'} busy={busy} onClose={onClose} onConfirm={save}>
    <div className="form-stack">{track && <label>Choose a playlist<select value={target} onChange={e => setTarget(e.target.value)} disabled={busy}><option value="new">Create a new playlist</option>{(query.data?.playlists || []).map(item => <option key={item.id} value={item.id}>{item.name} · {item.tracks.length} songs</option>)}</select></label>}
    {target === 'new' && <label>Playlist name<input autoFocus maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder="Road trips, favorites, rainy Sundays…" disabled={busy} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); save(); } }} /></label>}<ErrorBox error={error || query.error} /></div>
  </ConfirmDialog>;
}

export default function SongActions({ track, sourceId, notify, disabled = false }) {
  const client = useQueryClient(); const [adding, setAdding] = useState(false); const [busy, setBusy] = useState(false); const lock = useRef(false);
  const saved = useQuery({ queryKey: ['saved-songs'], queryFn: () => api('/saved-songs') });
  const isSaved = saved.data?.tracks?.some(item => item.id === track.id);
  async function toggle() {
    if (lock.current) return; lock.current = true; setBusy(true);
    try {
      if (isSaved) await api(`/saved-songs/${encodeURIComponent(track.id)}`, { method: 'DELETE' });
      else await api('/saved-songs', { method: 'POST', body: { track_id: track.id, source_id: sourceId } });
      await client.invalidateQueries({ queryKey: ['saved-songs'] });
      notify(isSaved ? 'Song removed from your saved songs.' : 'Song saved. Find it in Saved songs.');
    } catch (error) { notify(error.message, 'error'); }
    finally { lock.current = false; setBusy(false); }
  }
  return <><button className={`text-button ${isSaved ? 'liked' : ''}`} aria-label={`${isSaved ? 'Unsave' : 'Save'} song ${track.title}`} aria-pressed={!!isSaved} disabled={disabled || busy || saved.isLoading} onClick={toggle}><Heart size={15} fill={isSaved ? 'currentColor' : 'none'} />{isSaved ? 'Saved' : 'Save song'}</button><button className="text-button" aria-label={`Add ${track.title} to playlist`} disabled={disabled} onClick={() => setAdding(true)}><ListPlus size={16} />Add to playlist</button>{adding && <PlaylistDialog open onClose={() => setAdding(false)} track={track} sourceId={sourceId} notify={notify} />}</>;
}
