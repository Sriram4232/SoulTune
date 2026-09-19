import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { Music2, Play, Pause, SkipBack, SkipForward, Volume2, VolumeX, ListMusic, Headphones, X, ExternalLink } from 'lucide-react';
import { api, formatTime, safeUrl } from './api';
import { Artwork } from './components';

const PlayerContext = createContext(null);
export const usePlayer = () => useContext(PlayerContext);

export function PlayerProvider({ children, notify }) {
  const audioRef = useRef(null);
  const [current, setCurrent] = useState(null);
  const [queue, setQueue] = useState([]);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(0.7);
  const [fallback, setFallback] = useState(false);
  const [showQueue, setShowQueue] = useState(false);
  const state = useRef({ queue: [], index: 0, playlistId: null });
  const attempted = useRef(new Set());
  const recovering = useRef(false);
  const requestId = useRef(0);
  const notifyRef = useRef(notify);
  useEffect(() => { notifyRef.current = notify; }, [notify]);

  const playSource = useCallback(async (track, isFallback, request) => {
    const audio = audioRef.current;
    if (!audio || request !== requestId.current) return;
    const url = safeUrl(track.preview_url || track.audio_url);
    if (!url) throw new Error('Preview unavailable');
    attempted.current.add(track.id);
    setCurrent(track); setFallback(isFallback); setElapsed(0); setDuration(0);
    audio.src = url;
    try {
      await audio.play();
    } catch (error) {
      if (request !== requestId.current || error.name === 'AbortError') return;
      if (error.name === 'NotAllowedError') {
        setPlaying(false);
        notifyRef.current('Your browser paused playback. Press play to listen.');
        return;
      }
      throw error;
    }
  }, []);

  const useFallback = useCallback(async (request) => {
    if (recovering.current || request !== requestId.current) return;
    recovering.current = true;
    try {
      const data = await api('/library');
      if (request !== requestId.current) return;
      const available = (data.tracks || []).filter(
        track => !attempted.current.has(track.id) && safeUrl(track.preview_url || track.audio_url)
      );
      if (!available.length) {
        audioRef.current?.pause();
        audioRef.current?.removeAttribute('src');
        setPlaying(false);
        setCurrent(null);
        notifyRef.current('No playable audio is available. Add your music to fallback_songs, then rescan in Local library.', 'info');
        return;
      }
      for (let position = 0; position < available.length; position++) {
        if (request !== requestId.current) return;
        const track = available[position];
        try {
          await playSource(track, true, request);
          if (request !== requestId.current) return;
          const localQueue = available.slice(position);
          state.current = { queue: localQueue, index: 0, playlistId: null };
          setQueue(localQueue); setIndex(0);
          notifyRef.current(`Switched to your local library: ${track.title}.`, 'info');
          return;
        } catch { /* Try the next local file if this codec or recording cannot play. */ }
      }
      audioRef.current?.pause();
      audioRef.current?.removeAttribute('src');
      setPlaying(false);
      setCurrent(null);
      notifyRef.current('These local files could not play. Check the recordings or try MP3, WAV, or OGG files.', 'error');
    } catch (error) {
      if (request === requestId.current) {
        setPlaying(false);
        notifyRef.current(error.message, 'error');
      }
    } finally {
      recovering.current = false;
    }
  }, [playSource]);

  const start = useCallback(async (tracks, position = 0, playlistId = null) => {
    if (!tracks?.length) return;
    const next = Math.max(0, Math.min(position, tracks.length - 1));
    state.current = { queue: tracks, index: next, playlistId };
    setQueue(tracks); setIndex(next); attempted.current = new Set();
    const request = ++requestId.current;
    recovering.current = false;
    audioRef.current?.pause();
    audioRef.current?.removeAttribute('src');
    setCurrent(tracks[next]); setFallback(false); setElapsed(0); setDuration(0);
    if (tracks[next]?.source === 'spotify') {
      setPlaying(true);
      return;
    }
    try {
      await playSource(tracks[next], false, request);
    } catch {
      // Last.fm provides catalogue metadata/listening links, not a guaranteed
      // playable stream. Never replace the selected song with an unrelated
      // local track; fallback is reserved for local tracks whose file fails.
      if (tracks[next]?.source === 'local') {
        await useFallback(request);
      } else {
        setPlaying(false);
        notifyRef.current('This online track has no playable preview. Open its track link or choose a downloaded song from Local library.', 'info');
      }
    }
  }, [playSource, useFallback]);

  const move = useCallback((direction) => {
    const snapshot = state.current;
    if (!snapshot.queue.length) return;
    const next = (snapshot.index + direction + snapshot.queue.length) % snapshot.queue.length;
    start(snapshot.queue, next, snapshot.playlistId);
  }, [start]);

  useEffect(() => {
    const audio = new Audio();
    audio.preload = 'metadata';
    audio.volume = 0.7;
    audioRef.current = audio;
    const onTime = () => setElapsed(audio.currentTime || 0);
    const onMeta = () => setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnd = () => {
      if (state.current.index < state.current.queue.length - 1) move(1);
      else setPlaying(false);
    };
    const onError = () => {
      /* Rejected play promises are handled by start; subsequent stream errors use local files. */
      if (audio.currentTime > 0) useFallback(requestId.current);
    };
    audio.addEventListener('timeupdate', onTime);
    audio.addEventListener('loadedmetadata', onMeta);
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('ended', onEnd);
    audio.addEventListener('error', onError);
    return () => {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      audioRef.current = null;
    };
  }, [move, useFallback]);

  function toggle() {
    if (!current) return;
    if (current.source === 'spotify') {
      setPlaying(!playing);
      return;
    }
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) audio.pause();
    else if (audio.src && !audio.error) audio.play().catch(() => useFallback(requestId.current));
    else start(state.current.queue, state.current.index, state.current.playlistId);
  }

  const seek = value => {
    if (audioRef.current && duration) {
      audioRef.current.currentTime = Number(value);
      setElapsed(Number(value));
    }
  };

  const adjustVolume = value => {
    const next = Number(value);
    setVolume(next);
    if (audioRef.current) audioRef.current.volume = next;
  };

  const clear = () => {
    ++requestId.current;
    audioRef.current?.pause();
    setCurrent(null);
    setQueue([]);
    state.current = { queue: [], index: 0 };
    setPlaying(false);
  };

  function syncPlaylist(playlistId, tracks) {
    if (state.current.playlistId !== playlistId) return;
    const currentId = state.current.queue[state.current.index]?.id;
    const position = tracks.findIndex(track => track.id === currentId);
    if (position < 0) { clear(); return; }
    state.current = { queue: tracks, index: position, playlistId };
    setQueue(tracks); setIndex(position); setCurrent(tracks[position]);
  }

  const spotifyId = current?.source === 'spotify'
    ? (current.id?.replace(/^spotify_/, '') || current.external_url?.split('/track/')[1]?.split('?')[0])
    : null;

  return (
    <PlayerContext.Provider value={{ current, playing, start, toggle, clear, queue, index, syncPlaylist }}>
      {children}
      <footer className={`player ${!current ? 'player-idle' : ''}`} aria-label="Music player">
        {spotifyId ? (
          <div className="player-spotify-bar">
            <div className="player-track">
              <Artwork seed={current.id} className="player-art" imageUrl={current.image_url} />
              <div>
                <strong>{current.title}</strong>
                <span className="spotify-badge-text">
                  <span className="spotify-dot" /> {current.artist} · Spotify
                </span>
              </div>
            </div>
            <div className="player-spotify-iframe-wrap">
              <iframe
                key={spotifyId}
                src={`https://open.spotify.com/embed/track/${spotifyId}?utm_source=generator&theme=0`}
                width="100%"
                height="80"
                frameBorder="0"
                allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
                loading="lazy"
                title={`Spotify: ${current.title}`}
              />
            </div>
            <div className="player-spotify-controls">
              <button className="icon-button" aria-label="Previous track" onClick={() => move(-1)}>
                <SkipBack size={17} fill="currentColor" />
              </button>
              <button className="icon-button" aria-label="Next track" onClick={() => move(1)}>
                <SkipForward size={17} fill="currentColor" />
              </button>
              {safeUrl(current.external_url) && (
                <a
                  className="button primary small spotify-open-btn"
                  href={safeUrl(current.external_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <ExternalLink size={13} /> Spotify
                </a>
              )}
              <button
                className="icon-button"
                aria-label="Show playback queue"
                aria-expanded={showQueue}
                onClick={() => setShowQueue(!showQueue)}
              >
                <ListMusic size={18} />
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="player-track">
              {current
                ? <Artwork seed={current.id} className="player-art" imageUrl={current.image_url} />
                : <div className="player-art no-track"><Headphones size={21} /></div>
              }
              <div>
                <strong>{current?.title || 'A little quiet, for now.'}</strong>
                <span>
                  {current
                    ? `${current.artist}${fallback ? ' · Local fallback' : current.source === 'local' ? ' · Your library' : ' · Preview'}`
                    : 'Your next favorite is a feeling away.'
                  }
                </span>
              </div>
            </div>
            <div className="player-middle">
              <div className="player-buttons">
                <button className="icon-button" aria-label="Previous track" disabled={!current} onClick={() => move(-1)}>
                  <SkipBack size={17} fill="currentColor" />
                </button>
                <button className="player-play" aria-label={playing ? 'Pause' : 'Play'} disabled={!current} onClick={toggle}>
                  {playing ? <Pause size={17} fill="currentColor" /> : <Play size={17} fill="currentColor" />}
                </button>
                <button className="icon-button" aria-label="Next track" disabled={!current} onClick={() => move(1)}>
                  <SkipForward size={17} fill="currentColor" />
                </button>
              </div>
              <div className="player-timeline">
                <span>{formatTime(elapsed)}</span>
                <input
                  type="range"
                  min="0"
                  max={duration || 1}
                  step="0.1"
                  value={Math.min(elapsed, duration || 1)}
                  disabled={!duration}
                  onChange={event => seek(event.target.value)}
                  aria-label="Seek track"
                />
                <span>{formatTime(duration)}</span>
              </div>
            </div>
            <div className="player-extras">
              <button
                className="icon-button"
                aria-label="Show playback queue"
                aria-expanded={showQueue}
                onClick={() => setShowQueue(!showQueue)}
              >
                <ListMusic size={18} />
              </button>
              <span className="player-divider" />
              <button
                className="icon-button"
                aria-label={volume ? 'Mute' : 'Unmute'}
                onClick={() => adjustVolume(volume ? 0 : 0.7)}
              >
                {volume ? <Volume2 size={18} /> : <VolumeX size={18} />}
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={volume}
                onChange={event => adjustVolume(event.target.value)}
                aria-label="Volume"
              />
            </div>
          </>
        )}
        {showQueue && (
          <div className="queue-popover">
            <div className="section-heading">
              <h3>Up next <span>{queue.length}</span></h3>
              <button className="icon-button" aria-label="Close queue" onClick={() => setShowQueue(false)}>
                <X size={18} />
              </button>
            </div>
            {queue.length ? (
              <ol>
                {queue.map((track, n) => (
                  <li key={`${track.id}-${n}`}>
                    <button className={n === index ? 'active' : ''} onClick={() => start(queue, n)}>
                      <span>{String(n + 1).padStart(2, '0')}</span>
                      <div>
                        <strong>{track.title}</strong>
                        <small>{track.artist}</small>
                      </div>
                      {n === index && <Music2 size={16} />}
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted">Play a playlist or a local song to start your queue.</p>
            )}
          </div>
        )}
      </footer>
    </PlayerContext.Provider>
  );
}
