const get = id => document.getElementById(id);
let socket, audio, media, microphone, source, playbackAt = 0, ready = false;
let lastRole, lastEntry;
const sources = new Set();
function entry(role, text, append = false) {
  if (!append || role !== lastRole) {
    const row = document.createElement('div'); row.className = 'entry';
    const label = document.createElement('span'); label.className = 'label'; label.textContent = role;
    lastEntry = document.createElement('span'); row.append(label, lastEntry); get('log').append(row);
    lastRole = role;
  }
  lastEntry.textContent += text;
  get('log').scrollTop = get('log').scrollHeight;
}
function clearPlayback() {
  for (const node of sources) { try { node.stop(); } catch {} }
  sources.clear(); playbackAt = 0;
}
async function cleanup() {
  ready = false;
  media?.getTracks().forEach(track => track.stop()); media = null;
  microphone?.disconnect(); source?.disconnect(); clearPlayback();
  await audio?.close(); audio = null;
  get('start').disabled = false; get('stop').disabled = true; get('end').disabled = true;
}
get('start').onclick = async () => {
  get('start').disabled = true; get('status').textContent = 'Opening microphone and Codex…';
  try {
    media = await navigator.mediaDevices.getUserMedia({audio: {
      channelCount: 1, echoCancellation: true, noiseSuppression: true,
    }});
    audio = new AudioContext({sampleRate: 24000}); await audio.resume();
    if (audio.sampleRate !== 24000) throw new Error('Browser cannot provide 24 kHz audio');
    await audio.audioWorklet.addModule('/microphone.js');
    source = audio.createMediaStreamSource(media);
    microphone = new AudioWorkletNode(audio, 'microphone'); source.connect(microphone);
    microphone.connect(audio.destination); // Worklet outputs silence; keeps processing alive.
    socket = new WebSocket(`ws://${location.host}/voice`); socket.binaryType = 'arraybuffer';
    microphone.port.onmessage = ({data}) => {
      if (ready && socket.readyState === WebSocket.OPEN) {
        if (socket.bufferedAmount > 96000) {
          get('status').textContent = 'Audio connection fell behind; session stopped.';
          socket.close(); return;
        }
        socket.send(data);
      }
    };
    socket.onmessage = ({data}) => {
      if (data instanceof ArrayBuffer) {
        if (!audio) return;
        const pcm = new Int16Array(data), buffer = audio.createBuffer(1, pcm.length, 24000);
        const floats = buffer.getChannelData(0);
        for (let i = 0; i < pcm.length; i++) floats[i] = pcm[i] / 32768;
        const node = audio.createBufferSource(); node.buffer = buffer; node.connect(audio.destination);
        playbackAt = Math.max(playbackAt, audio.currentTime + .02);
        node.start(playbackAt); playbackAt += buffer.duration;
        sources.add(node); node.onended = () => sources.delete(node);
        return;
      }
      const event = JSON.parse(data);
      if (event.kind === 'ready') {
        ready = true; get('status').textContent = 'Listening · 10-minute session limit';
        get('stop').disabled = false; get('end').disabled = false;
      } else if (event.kind === 'transcript') {
        entry(event.type.includes('input_') ? 'YOU' : 'GPT-LIVE', event.text, true);
      } else if (event.kind === 'delegation_result') entry('CODEX RESULT', event.result);
      else if (event.kind === 'stop') entry('EXECUTOR', event.receipt.simulation_success === true
        ? 'Simulator stop confirmed.' : 'Stop requested; not confirmed.');
      else if (event.kind === 'error') entry('ERROR', event.text);
    };
    socket.onclose = async () => { await cleanup(); get('status').textContent = 'Session ended.'; };
    socket.onerror = () => entry('ERROR', 'Voice connection failed. Check the local server.');
  } catch (error) {
    get('status').textContent = error.message; socket?.close(); await cleanup();
  }
};
get('stop').onclick = () => { clearPlayback(); socket?.send('stop'); };
get('end').onclick = () => { ready = false; socket?.send('close'); media?.getTracks().forEach(t => t.stop()); };
setInterval(() => { if (!document.hidden) get('camera').src = `/camera.jpg?t=${Date.now()}`; }, 1500);
window.addEventListener('beforeunload', () => socket?.close());
