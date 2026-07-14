/// <reference types="vite/client" />

declare module '*.geojson' {
  const value: {
    type: string
    features: unknown[]
  }
  export default value
}
