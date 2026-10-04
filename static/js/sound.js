// Move sounds, synthesised with the Web Audio API (no audio files). Created on first use, after a user gesture.
let ctx = null;
let enabled = true;

export function setSoundEnabled(on) { enabled = !!on; }

function audio() {
  if (!ctx) {
    try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return null; }
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

// A wooden "tock": a short burst of filtered noise plus a low thump.
function tock({ noiseHz = 1400, thumpHz = 170, volume = 0.5, length = 0.1, delay = 0 } = {}) {
  const c = enabled && audio();
  if (!c) return;
  const t = c.currentTime + delay;
  const frames = Math.max(1, Math.floor(c.sampleRate * length));
  const buffer = c.createBuffer(1, frames, c.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < frames; i++) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / frames, 3);
  const noise = c.createBufferSource(); noise.buffer = buffer;
  const band = c.createBiquadFilter(); band.type = "bandpass"; band.frequency.value = noiseHz; band.Q.value = 0.8;
  const g1 = c.createGain(); g1.gain.value = volume;
  noise.connect(band).connect(g1).connect(c.destination);
  noise.start(t);

  const osc = c.createOscillator(); osc.type = "sine";
  osc.frequency.setValueAtTime(thumpHz * 1.6, t); osc.frequency.exponentialRampToValueAtTime(thumpHz, t + 0.05);
  const g2 = c.createGain();
  g2.gain.setValueAtTime(volume * 0.9, t); g2.gain.exponentialRampToValueAtTime(0.001, t + length * 1.3);
  osc.connect(g2).connect(c.destination);
  osc.start(t); osc.stop(t + length * 1.4);
}

function tone(freq, { delay = 0, length = 0.18, volume = 0.18, type = "triangle" } = {}) {
  const c = enabled && audio();
  if (!c) return;
  const t = c.currentTime + delay;
  const osc = c.createOscillator(); osc.type = type; osc.frequency.value = freq;
  const g = c.createGain();
  g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(volume, t + 0.015); g.gain.exponentialRampToValueAtTime(0.0001, t + length);
  osc.connect(g).connect(c.destination);
  osc.start(t); osc.stop(t + length + 0.02);
}

export const sounds = {
  move: () => tock(),
  capture: () => tock({ noiseHz: 900, thumpHz: 120, volume: 0.75, length: 0.14 }),
  castle: () => { tock(); tock({ delay: 0.11, noiseHz: 1100 }); },
  check: () => { tock({ noiseHz: 900, thumpHz: 120, volume: 0.7 }); tone(880, { delay: 0.05, length: 0.16 }); },
  promote: () => { tock(); tone(660, { delay: 0.05 }); tone(990, { delay: 0.14 }); },
  end: () => { tone(523, { length: 0.3 }); tone(659, { delay: 0.12, length: 0.3 }); tone(784, { delay: 0.24, length: 0.5 }); },
  good: () => { tone(660, { length: 0.12 }); tone(880, { delay: 0.09, length: 0.22 }); },
  bad: () => { tone(220, { length: 0.25, type: "sawtooth", volume: 0.1 }); },
};

/** Play the right sound for a move written in SAN ("Nxe5+", "O-O", "e8=Q"). */
export function soundForSan(san = "") {
  if (/#/.test(san)) return sounds.end();
  if (/\+/.test(san)) return sounds.check();
  if (/=/.test(san)) return sounds.promote();
  if (/^O-O/.test(san)) return sounds.castle();
  if (/x/.test(san)) return sounds.capture();
  return sounds.move();
}
