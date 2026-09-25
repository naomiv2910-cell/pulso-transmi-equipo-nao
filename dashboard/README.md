# Observatorio Pulso TransMi · Nao

Dashboard: https://pulso-transmi-nao.vercel.app

Next.js muestra el informe público de la rama `dashboard-data`, archivo `dashboard.json`. No necesita claves de Pulso ni acceso directo a Supabase. La página consulta el informe cada minuto; indica si lleva más de dos horas sin actualizarse.

## Cálculo y actualización

El workflow `analytics.yml` sincroniza las observaciones publicadas usando un cursor persistente, calcula las métricas y publica un JSON con campos permitidos. El vigilante lo solicita al renovarse, aproximadamente cada 45 minutos mientras esté activo. También se puede ejecutar manualmente desde Actions. Las claves permanecen en GitHub Actions Secrets.

Drift: compara las últimas 24 horas virtuales con la referencia hasta el fin del entrenamiento. Normaliza la demanda por estación, día de semana y hora de Bogotá; calcula PSI y cambio de media estandarizado. Requiere 28 días de referencia y 96 observaciones recientes por estación. PSI de 0,20/0,30 y cambio de media de 0,5/1 son alertas moderadas/fuertes. Son umbrales heurísticos; no demuestran concept drift ni activan reentrenamiento automático.

Precisión: usa entregas del modelo champion con verdad completa en las últimas 24 horas virtuales. Accuracy es el promedio por estación de `100 * max(0, 1 - WAPE)`. Excluye ausencias y por tanto no reproduce el ranking oficial. Las fechas de los targets pertenecen al reloj virtual del reto; las fechas de envíos e informes corresponden al reloj real.

## Desarrollo y publicación

```sh
npm ci
npm run lint
npm run build
npm run dev
```

Publicación desde esta carpeta, con la sesión de Vercel iniciada:

```sh
npx vercel@60.1.1 link --scope nao-326d --project pulso-transmi-nao
npx vercel@60.1.1 deploy --prod --yes --scope nao-326d
```

El despliegue inicial se hizo con CLI. La integración GitHub–Vercel requiere conectar la cuenta de GitHub en Vercel; los datos del dashboard se actualizan sin redesplegar.
