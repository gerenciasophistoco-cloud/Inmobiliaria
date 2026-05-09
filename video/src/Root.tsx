import React from 'react';
import { Composition } from 'remotion';
import { PropertyReel, VideoProps } from './PropertyReel';

const PHOTO_FRAMES = 120;
const BLACK_GAP    = 30;
const OUTRO        = 210;

const defaultProps: VideoProps = {
  fotos: [],
  labels: [],
  precio: '$ 0',
  ciudad: 'Ciudad',
  tipo: 'Propiedad',
  operacion: 'Venta',
  direccion: '',
  habitaciones: '',
  banos: '',
  m2_construidos: '',
  estrato: '',
  nombre_agente: 'Agente',
  telefono: '',
  amenidades: [],
  foto_agente: '',
  frase_inspiradora: '',
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="PropertyReel"
    component={PropertyReel}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={720}
    defaultProps={defaultProps}
    calculateMetadata={async ({ props }) => {
      const photoCount = Math.min(((props as VideoProps).fotos || []).filter(Boolean).length, 4);
      return {
        durationInFrames: photoCount * PHOTO_FRAMES + BLACK_GAP + OUTRO,
      };
    }}
  />
);
