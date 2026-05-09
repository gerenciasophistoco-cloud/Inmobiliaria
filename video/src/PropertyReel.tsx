import {
  AbsoluteFill,
  Img,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  Sequence,
} from 'remotion';
import React from 'react';

export interface VideoProps {
  fotos: string[];
  labels?: string[];
  precio: string;
  ciudad: string;
  tipo: string;
  operacion: string;
  direccion?: string;
  habitaciones?: string;
  banos?: string;
  m2_construidos?: string;
  estrato?: string;
  nombre_agente: string;
  telefono: string;
  email?: string;
  amenidades?: string[];
  logo?: string;
  foto_agente?: string;
  nombre_inmobiliaria?: string;
  frase_inspiradora?: string;
}

const PHOTO_FRAMES = 120; // 4 s @ 30 fps
const FADE        = 18;
const BLACK_GAP   = 30;  // 1 s negro puro antes del outro
const OUTRO       = 210; // 7 s para la pantalla de contacto

// ─── Ken Burns ────────────────────────────────────────────────────────────────
const KenBurns: React.FC<{ src: string; seed: number }> = ({ src, seed }) => {
  const f = useCurrentFrame();
  const t = f / PHOTO_FRAMES;
  const moves = [
    { xs: [0, -3],  ys: [0, -2], ss: [1.08, 1.15] },
    { xs: [3, 0],   ys: [1, -1], ss: [1.12, 1.05] },
    { xs: [-2, 2],  ys: [0, 2],  ss: [1.1,  1.18] },
    { xs: [1, -2],  ys: [-1, 1], ss: [1.15, 1.08] },
  ];
  const m = moves[seed % 4];
  return (
    <AbsoluteFill>
      <Img src={src} style={{
        width: '100%', height: '100%', objectFit: 'cover',
        transform: `scale(${interpolate(t,[0,1],m.ss)}) translate(${interpolate(t,[0,1],m.xs)}%,${interpolate(t,[0,1],m.ys)}%)`,
        transformOrigin: 'center',
      }} />
    </AbsoluteFill>
  );
};

// ─── FadeSlide ────────────────────────────────────────────────────────────────
const FadeSlide: React.FC<{ children: React.ReactNode; dur?: number; noOut?: boolean }> = ({
  children, dur = PHOTO_FRAMES, noOut = false,
}) => {
  const f  = useCurrentFrame();
  const op = noOut
    ? interpolate(f, [0, FADE], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
    : interpolate(f, [0, FADE, dur - FADE, dur], [0, 1, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return <AbsoluteFill style={{ opacity: op }}>{children}</AbsoluteFill>;
};

// ─── Appear ───────────────────────────────────────────────────────────────────
const Appear: React.FC<{ delay?: number; style?: React.CSSProperties; children: React.ReactNode }> = ({
  delay = 0, style, children,
}) => {
  const f  = useCurrentFrame();
  const op = interpolate(f, [delay, delay + 18], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const ty = interpolate(f, [delay, delay + 18], [24, 0],  { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return <div style={{ opacity: op, transform: `translateY(${ty}px)`, ...style }}>{children}</div>;
};

// ─── Header persistente ───────────────────────────────────────────────────────
const Header: React.FC<Pick<VideoProps,'logo'|'nombre_inmobiliaria'|'tipo'|'operacion'|'precio'>> = ({
  logo, nombre_inmobiliaria, tipo, operacion, precio,
}) => (
  <div style={{
    position: 'absolute', top: 0, left: 0, right: 0, zIndex: 20,
    padding: '48px 56px 80px',
    background: 'linear-gradient(180deg,rgba(0,0,0,.72) 0%,transparent 100%)',
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
  }}>
    {/* Izquierda: logo + empresa */}
    <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
      {logo ? (
        <Img src={logo} style={{ height: 52, width: 52, objectFit: 'contain' }} />
      ) : null}
      {nombre_inmobiliaria ? (
        <span style={{
          fontFamily: 'system-ui,sans-serif', fontSize: 26, fontWeight: 300,
          letterSpacing: '0.22em', color: 'rgba(255,255,255,0.88)', textTransform: 'uppercase',
        }}>
          {nombre_inmobiliaria}
        </span>
      ) : null}
    </div>

    {/* Derecha: tipo + operacion + precio */}
    <div style={{ textAlign: 'right' }}>
      <div style={{
        fontFamily: 'system-ui,sans-serif', fontSize: 18, fontWeight: 700,
        letterSpacing: '0.18em', color: 'rgba(255,255,255,0.55)', textTransform: 'uppercase',
        marginBottom: 6,
      }}>
        {tipo} · {operacion}
      </div>
      <div style={{
        fontFamily: 'system-ui,sans-serif', fontSize: 36, fontWeight: 800,
        letterSpacing: '-0.01em', color: '#d4af37',
      }}>
        {precio}
      </div>
    </div>
  </div>
);

// ─── Pie de foto (zone label) ─────────────────────────────────────────────────
const ZoneLabel: React.FC<{ label: string }> = ({ label }) => {
  const f  = useCurrentFrame();
  const op = interpolate(f, [10, 24], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const tx = interpolate(f, [10, 24], [-20, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <div style={{
      position: 'absolute', bottom: 220, left: 56, opacity: op,
      transform: `translateX(${tx}px)`, zIndex: 10,
    }}>
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 0,
        borderLeft: '4px solid #d4af37',
        paddingLeft: 20,
      }}>
        <span style={{
          fontFamily: 'system-ui,sans-serif', fontSize: 22, fontWeight: 700,
          letterSpacing: '0.22em', color: 'rgba(255,255,255,0.75)',
          textTransform: 'uppercase', background: 'rgba(0,0,0,0.35)', padding: '8px 20px 8px 0',
        }}>
          {label}
        </span>
      </div>
    </div>
  );
};

// ─── Info por foto ────────────────────────────────────────────────────────────
type SlideInfoProps = { index: number } & VideoProps;

const SlideInfo: React.FC<SlideInfoProps> = (p) => {
  const { index, precio, ciudad, tipo, operacion, direccion,
          habitaciones, banos, m2_construidos, estrato, amenidades = [] } = p;

  if (index === 0) {
    return (
      <div style={{ position: 'absolute', bottom: 130, left: 56, right: 56 }}>
        <Appear delay={6} style={{
          fontFamily: 'system-ui,sans-serif', fontSize: 100, fontWeight: 800,
          lineHeight: 1, color: '#fff', letterSpacing: '-0.025em',
          textTransform: 'uppercase', textShadow: '0 4px 28px rgba(0,0,0,.6)',
          marginBottom: 18,
        }}>
          {ciudad}
        </Appear>
        {direccion ? (
          <Appear delay={14} style={{
            fontFamily: 'system-ui,sans-serif', fontSize: 30, fontWeight: 400,
            color: 'rgba(255,255,255,0.55)', marginBottom: 22, letterSpacing: '0.04em',
          }}>
            {direccion}
          </Appear>
        ) : null}
        <Appear delay={22} style={{
          fontFamily: 'system-ui,sans-serif', fontSize: 68, fontWeight: 700,
          letterSpacing: '-0.01em', color: '#d4af37',
          textShadow: '0 2px 16px rgba(0,0,0,.5)',
        }}>
          {precio}
        </Appear>
      </div>
    );
  }

  if (index === 1) {
    const stats = [
      habitaciones && habitaciones !== '-' ? { label: 'Habitaciones', value: habitaciones } : null,
      banos && banos !== '-'               ? { label: 'Baños',        value: banos }        : null,
      m2_construidos && m2_construidos !== '-' ? { label: 'M²',      value: m2_construidos } : null,
      estrato && estrato !== '-'           ? { label: 'Estrato',      value: estrato }       : null,
    ].filter(Boolean) as { label: string; value: string }[];

    return (
      <div style={{ position: 'absolute', bottom: 130, left: 56, right: 56 }}>
        <Appear delay={6} style={{
          fontFamily: 'system-ui,sans-serif', fontSize: 20, fontWeight: 700,
          letterSpacing: '0.22em', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', marginBottom: 32,
        }}>
          Características
        </Appear>
        <div style={{ display: 'flex', gap: 56, flexWrap: 'wrap' }}>
          {stats.map((s, i) => (
            <Appear key={i} delay={10 + i * 8} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span style={{
                fontFamily: 'system-ui,sans-serif', fontSize: 16, fontWeight: 700,
                letterSpacing: '0.2em', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase',
              }}>
                {s.label}
              </span>
              <span style={{
                fontFamily: 'system-ui,sans-serif', fontSize: 80, fontWeight: 800,
                lineHeight: 1, color: '#fff', letterSpacing: '-0.02em',
              }}>
                {s.value}
              </span>
            </Appear>
          ))}
        </div>
      </div>
    );
  }

  if (index === 2) {
    return (
      <div style={{ position: 'absolute', bottom: 130, left: 56, right: 56 }}>
        <Appear delay={6} style={{
          fontFamily: 'system-ui,sans-serif', fontSize: 20, fontWeight: 700,
          letterSpacing: '0.22em', color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', marginBottom: 28,
        }}>
          Amenidades
        </Appear>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
          {amenidades.slice(0, 6).map((a, i) => (
            <Appear key={i} delay={12 + i * 7} style={{
              fontFamily: 'system-ui,sans-serif', fontSize: 24, fontWeight: 600,
              color: 'rgba(255,255,255,0.85)',
              background: 'rgba(255,255,255,0.08)',
              border: '1px solid rgba(255,255,255,0.18)',
              padding: '12px 26px', letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>
              {a}
            </Appear>
          ))}
        </div>
      </div>
    );
  }

  // index >= 3: tipo + ciudad a modo de cierre de galería
  return (
    <div style={{ position: 'absolute', bottom: 130, left: 56, right: 56 }}>
      <Appear delay={8} style={{
        fontFamily: 'system-ui,sans-serif', fontSize: 52, fontWeight: 700,
        color: '#fff', letterSpacing: '-0.01em', textTransform: 'uppercase',
        textShadow: '0 4px 20px rgba(0,0,0,.55)', marginBottom: 16,
      }}>
        {tipo} en {operacion}
      </Appear>
      <Appear delay={18} style={{
        fontFamily: 'system-ui,sans-serif', fontSize: 30, fontWeight: 400,
        color: 'rgba(255,255,255,0.5)', letterSpacing: '0.04em',
      }}>
        {ciudad}{direccion ? ` · ${direccion}` : ''}
      </Appear>
    </div>
  );
};

// ─── Photo slide completo ─────────────────────────────────────────────────────
const PhotoSlide: React.FC<{ foto: string; index: number; label?: string } & VideoProps> = ({
  foto, index, label, ...props
}) => (
  <AbsoluteFill>
    <KenBurns src={foto} seed={index} />
    <AbsoluteFill style={{
      background: 'linear-gradient(180deg,rgba(0,0,0,.58) 0%,transparent 22%,transparent 48%,rgba(0,0,0,.88) 100%)',
    }} />
    <Header
      logo={props.logo} nombre_inmobiliaria={props.nombre_inmobiliaria}
      tipo={props.tipo} operacion={props.operacion} precio={props.precio}
    />
    {label ? <ZoneLabel label={label} /> : null}
    <SlideInfo index={index} foto={foto} {...props} />
  </AbsoluteFill>
);

// ─── Contact slide ────────────────────────────────────────────────────────────
const ContactSlide: React.FC<VideoProps> = ({
  nombre_agente, telefono, email, logo, nombre_inmobiliaria,
  foto_agente, frase_inspiradora, amenidades = [],
}) => (
  <AbsoluteFill style={{
    background: 'linear-gradient(160deg,#0d0d0d 0%,#1a1510 55%,#0d0d0d 100%)',
    alignItems: 'center', justifyContent: 'center',
    flexDirection: 'column', padding: '60px 80px',
  }}>
    {/* Barra dorada superior */}
    <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 5,
      background: 'linear-gradient(90deg,#d4af37,transparent)' }} />

    {/* Logo + empresa */}
    <Appear delay={2} style={{ display: 'flex', alignItems: 'center', gap: 22, marginBottom: 52 }}>
      {logo ? <Img src={logo} style={{ height: 60, objectFit: 'contain', maxWidth: 180 }} /> : null}
      {nombre_inmobiliaria ? (
        <span style={{
          fontFamily: 'system-ui,sans-serif', fontSize: 26, fontWeight: 300,
          color: 'rgba(255,255,255,0.42)', letterSpacing: '0.24em', textTransform: 'uppercase',
        }}>
          {nombre_inmobiliaria}
        </span>
      ) : null}
    </Appear>

    {/* Foto del agente */}
    {foto_agente ? (
      <Appear delay={8} style={{ marginBottom: 40 }}>
        <div style={{
          width: 172, height: 172, borderRadius: '50%', overflow: 'hidden',
          border: '3px solid rgba(212,175,55,0.65)',
          boxShadow: '0 0 48px rgba(212,175,55,0.22), 0 8px 32px rgba(0,0,0,0.6)',
        }}>
          <Img src={foto_agente} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </div>
      </Appear>
    ) : null}

    {/* Nombre */}
    <Appear delay={14} style={{
      fontFamily: 'system-ui,sans-serif', fontSize: 76, fontWeight: 800,
      color: '#fff', textAlign: 'center', lineHeight: 1.1, marginBottom: 20,
    }}>
      {nombre_agente}
    </Appear>

    {/* Línea dorada */}
    <Appear delay={20} style={{ width: 80, height: 4, background: '#d4af37', borderRadius: 2, marginBottom: 30 }}>
      <span />
    </Appear>

    {/* Título */}
    <Appear delay={24} style={{
      fontFamily: 'system-ui,sans-serif', fontSize: 24, fontWeight: 400,
      color: 'rgba(255,255,255,0.38)', letterSpacing: '0.24em',
      textTransform: 'uppercase', marginBottom: 50,
    }}>
      Agente Inmobiliario
    </Appear>

    {/* Teléfono */}
    <Appear delay={30} style={{
      fontFamily: 'system-ui,sans-serif', fontSize: 60, fontWeight: 700,
      color: '#d4af37', marginBottom: 18, textAlign: 'center',
    }}>
      {telefono}
    </Appear>

    {/* Email */}
    {email ? (
      <Appear delay={36} style={{
        fontFamily: 'system-ui,sans-serif', fontSize: 32, fontWeight: 400,
        color: 'rgba(255,255,255,0.48)', textAlign: 'center', marginBottom: 40,
      }}>
        {email}
      </Appear>
    ) : null}

    {/* Frase inspiradora */}
    {frase_inspiradora ? (
      <Appear delay={44} style={{
        position: 'absolute', bottom: 80, left: 80, right: 80,
        fontFamily: 'Georgia,Times New Roman,serif',
        fontSize: 28, fontWeight: 300, fontStyle: 'italic',
        color: 'rgba(255,255,255,0.28)', textAlign: 'center', lineHeight: 1.65,
      }}>
        "{frase_inspiradora}"
      </Appear>
    ) : (
      /* Amenidades como fallback si no hay frase */
      amenidades.length > 0 ? (
        <Appear delay={44} style={{
          position: 'absolute', bottom: 80, left: 0, right: 0,
          display: 'flex', flexWrap: 'wrap', gap: 14,
          justifyContent: 'center', padding: '0 80px',
        }}>
          {amenidades.slice(0, 5).map((a, i) => (
            <span key={i} style={{
              fontFamily: 'system-ui,sans-serif', fontSize: 22, fontWeight: 600,
              color: 'rgba(255,255,255,0.4)', background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.1)', padding: '8px 22px',
              letterSpacing: '0.1em', textTransform: 'uppercase',
            }}>
              {a}
            </span>
          ))}
        </Appear>
      ) : null
    )}

    {/* Barra dorada inferior */}
    <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 5,
      background: 'linear-gradient(90deg,#d4af37,transparent)' }} />
  </AbsoluteFill>
);

// ─── Composición principal ────────────────────────────────────────────────────
export const PropertyReel: React.FC<VideoProps> = (props) => {
  const { fotos, labels = [] } = props;
  const validFotos  = (fotos || []).filter(Boolean).slice(0, 4);
  const outroStart  = validFotos.length * PHOTO_FRAMES + BLACK_GAP;

  return (
    <AbsoluteFill style={{ background: '#0a0a0a' }}>
      {/* Slides de fotos */}
      {validFotos.map((foto, i) => (
        <Sequence key={i} from={i * PHOTO_FRAMES} durationInFrames={PHOTO_FRAMES}>
          <FadeSlide dur={PHOTO_FRAMES}>
            <PhotoSlide foto={foto} index={i} label={labels[i] || ''} {...props} />
          </FadeSlide>
        </Sequence>
      ))}

      {/* Slide de contacto (comienza tras BLACK_GAP frames de negro puro) */}
      <Sequence from={outroStart} durationInFrames={OUTRO}>
        <FadeSlide dur={OUTRO} noOut>
          <ContactSlide {...props} />
        </FadeSlide>
      </Sequence>
    </AbsoluteFill>
  );
};
