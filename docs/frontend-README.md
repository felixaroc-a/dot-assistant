# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

You can also install [eslint-plugin-react-x](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://github.com/Rel1cx/eslint-react/tree/main/packages/plugins/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])
```

## Nordik — autenticación (JWT)

La pantalla de **login del producto** usa **cédula + contraseña** contra el backend (`VITE_API_BASE_URL`) y persiste el **JWT** en `localStorage` (clave `nordik_jwt_session_v1`). **Firebase Auth ya no bloquea el acceso** a la app; el Admin SDK del backend sigue usándose para Firestore y el flujo OAuth de Google.

Perfiles en Firestore van ligados al **UUID del cliente** (`cliente_id` / campo `sub` del JWT).

Contrato (`POST /v1/auth/login`, variables de servidor): ver [`architecture-session.md`](./architecture-session.md).

## Entrega USB de cliente (Windows)

**Vendedores:** usar solo el panel `auto-venta1` en el puerto **8001** (ficha del cliente → provisionar USB). Guía completa: [`usb-provision-entrega.md`](./usb-provision-entrega.md).

**Soporte / ingeniería** (contingencia, no flujo comercial):

```bash
npm run desktop:provisioner   # app Electron Provisioner (NORDIK_PROVISIONER=1)
npm run usb:provision-delivery -- --require-registered
powershell -ExecutionPolicy Bypass -File .\scripts\provision-pendrive-delivery.ps1
```

El script de provisión:
- valida (si hay API disponible) que el serial esté registrado;
- crea/verifica `nordik.vault` en el USB (llave física anti-clonación);
- copia el último instalador `.exe` desde `frontend/release` al USB.

Opciones útiles del CLI:
- `--serial <SERIAL>`: cuando hay más de un USB conectado.
- `--installer <ruta.exe>`: usar un instalador específico.
- `--recovery-out <ruta.txt>`: guardar la recovery key generada.
- `--force`: regenerar vault aunque ya exista uno válido.

