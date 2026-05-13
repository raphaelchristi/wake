/* eslint-env node */
module.exports = {
  root: true,
  extends: ["next/core-web-vitals", "next/typescript"],
  ignorePatterns: [
    ".next/",
    "node_modules/",
    "src/lib/api/generated.ts",
    "tests/e2e/",
    "playwright.config.ts",
  ],
  rules: {
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/consistent-type-imports": [
      "error",
      { prefer: "type-imports", fixStyle: "inline-type-imports" },
    ],
    "react/no-unescaped-entities": "off",
  },
};
