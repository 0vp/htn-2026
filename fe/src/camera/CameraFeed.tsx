import { useEffect, useState, type FormEvent } from 'react';

type Signal = 'none' | 'connecting' | 'live' | 'lost';

const KEY = 'htn.cameraUrl';

function initialUrl(): string {
  const fromQuery = new URLSearchParams(location.search).get('camera');
  if (fromQuery) return fromQuery;
  try {
    return localStorage.getItem(KEY) ?? import.meta.env.VITE_CAMERA_URL ?? '';
  } catch {
    return import.meta.env.VITE_CAMERA_URL ?? '';
  }
}

function remember(url: string) {
  try {
    if (url) localStorage.setItem(KEY, url);
    else localStorage.removeItem(KEY);
  } catch {
    // Convenience only.
  }
}

/**
 * MJPEG picture-in-picture for the ESP32-S3 CAM. The stock CameraWebServer sketch serves
 * `http://<board-ip>:81/stream`; the browser decodes multipart JPEG natively in an <img>.
 */
export function CameraFeed() {
  const [url, setUrl] = useState(initialUrl);
  const [draft, setDraft] = useState(url);
  const [signal, setSignal] = useState<Signal>(url ? 'connecting' : 'none');
  const [nonce, setNonce] = useState(0);

  // Retry a lost stream every 3 s; the board drops clients when Wi-Fi hiccups.
  useEffect(() => {
    if (signal !== 'lost') return;
    const timer = setTimeout(() => {
      setSignal('connecting');
      setNonce((n) => n + 1);
    }, 3000);
    return () => clearTimeout(timer);
  }, [signal]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = draft.trim();
    remember(next);
    setUrl(next);
    setSignal(next ? 'connecting' : 'none');
    setNonce((n) => n + 1);
  };

  const src = url ? `${url}${url.includes('?') ? '&' : '?'}_=${nonce}` : '';
  const status = { none: 'No camera', connecting: 'Connecting', live: 'Live', lost: 'No signal · retrying' }[signal];

  return (
    <figure className="hairline-light w-[300px] border bg-blue-deep/80 backdrop-blur-sm">
      <div className="relative aspect-[4/3] bg-black/30">
        {src && (
          <img
            key={src}
            src={src}
            alt="Robot camera"
            onLoad={() => setSignal('live')}
            onError={() => setSignal('lost')}
            className={`absolute inset-0 size-full object-cover ${signal === 'live' ? '' : 'opacity-0'}`}
          />
        )}
        {signal !== 'live' && (
          <div className="absolute inset-0 grid place-items-center">
            <p className="label text-[10px] text-blue-soft">{status}</p>
          </div>
        )}
      </div>
      <figcaption className="hairline-light flex items-center gap-2 border-t px-2 py-1.5">
        <span className={`size-1.5 shrink-0 ${signal === 'live' ? 'bg-white' : signal === 'none' ? 'bg-blue-soft' : 'bg-signal'}`} />
        <form onSubmit={submit} className="flex min-w-0 flex-1 items-center gap-2">
          <input
            aria-label="Camera stream URL"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="http://esp32-cam.local:81/stream"
            spellCheck={false}
            className="min-w-0 flex-1 bg-transparent font-mono text-[10px] text-white placeholder:text-white/40 focus:outline-none"
          />
          <button type="submit" className="label text-[10px] text-blue-soft hover:text-white">
            Set
          </button>
        </form>
      </figcaption>
    </figure>
  );
}
