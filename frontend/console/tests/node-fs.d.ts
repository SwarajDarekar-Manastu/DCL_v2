// The one Node API the tests use to read source files (no @types/node in this package).
declare module 'node:fs' {
	export function readFileSync(path: string, encoding: 'utf8'): string;
}
