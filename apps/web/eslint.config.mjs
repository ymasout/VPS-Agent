import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });
const config = [
  { ignores: [".next/**", "node_modules/**", "coverage/**"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default config;
