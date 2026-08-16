/**
 * T14 OpenAPI drift detection test.
 *
 * Verifies that the generated TypeScript types (web/src/generated/openapi.ts)
 * are up-to-date with the current FastAPI OpenAPI schema. If this test fails,
 * run `npm run openapi` from the web/ directory to regenerate.
 */
import { describe, it, expect } from 'vitest';
import { execSync } from 'child_process';
import { readFileSync } from 'fs';
import { resolve } from 'path';

describe('OpenAPI type generation drift', () => {
  it('generated openapi.ts matches current backend schema', () => {
    // process.cwd() is set by vitest to the web/ directory
    const webDir = process.cwd();
    const projectRoot = resolve(webDir, '..');
    const generatedPath = resolve(webDir, 'src', 'generated', 'openapi.ts');

    // Read the current generated file
    const currentContent = readFileSync(generatedPath, 'utf-8');

    // Re-export the schema from Python
    execSync('python scripts/export_openapi.py', { cwd: projectRoot, stdio: 'pipe' });

    // Re-generate the TypeScript file to a temp location
    const tmpOutput = resolve(webDir, 'src', 'generated', 'openapi.ts.tmp');
    execSync(
      `npx openapi-typescript src/generated/openapi-schema.json -o src/generated/openapi.ts.tmp`,
      { cwd: webDir, stdio: 'pipe' },
    );

    const freshContent = readFileSync(tmpOutput, 'utf-8');

    // Cleanup tmp
    execSync(`rm -f ${tmpOutput}`);

    expect(freshContent).toBe(currentContent);
  });
});
