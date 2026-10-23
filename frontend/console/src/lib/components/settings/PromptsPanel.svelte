<script lang="ts">
	// Settings › Prompts: the versioned prompt files with the in-use marker, a side-by-side diff between versions,
	// and "run on sample" (one real model call). Read-only: prompts change by a new file in the repository.
	import {
		ApiError,
		diffPrompts,
		getPrompt,
		listPrompts,
		runPrompt,
		type PromptRunResult,
		type PromptText,
		type PromptVersion
	} from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';
	import { groupPrompts, sideBySide, type DiffRow, type PromptGroup } from './prompts';

	let list = $state<PromptVersion[]>([]);
	let error = $state('');
	let selected = $state<PromptVersion | null>(null);
	let text = $state<PromptText | null>(null);
	let compareTo = $state('');
	let diff = $state<DiffRow[] | null>(null);
	let variables = $state<Record<string, string>>({});
	let tier = $state<'flash' | 'lite'>('flash');
	let image = $state<string | null>(null);
	let running = $state(false);
	let result = $state<PromptRunResult | null>(null);
	let runError = $state('');

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));
	let groups = $derived<PromptGroup[]>(groupPrompts(list));
	let siblings = $derived(selected ? (groups.find((g) => g.area === selected!.area && g.name === selected!.name)?.versions ?? []) : []);

	$effect(() => {
		listPrompts()
			.then((l) => (list = l))
			.catch((e) => (error = describe(e)));
	});

	async function open(p: PromptVersion) {
		selected = p;
		text = null;
		diff = null;
		compareTo = '';
		result = null;
		runError = '';
		image = null;
		variables = Object.fromEntries(p.variables.map((v) => [v, '']));
		try {
			text = await getPrompt(p.area, p.version);
		} catch (e) {
			error = describe(e);
		}
	}

	async function compare(other: string) {
		compareTo = other;
		diff = null;
		if (!selected || !other) return;
		try {
			diff = sideBySide((await diffPrompts(selected.area, other, selected.version)).unified);
		} catch (e) {
			error = describe(e);
		}
	}

	function pickImage(event: Event) {
		const file = (event.currentTarget as HTMLInputElement).files?.[0];
		image = null;
		if (!file) return;
		const reader = new FileReader();
		reader.onload = () => (image = String(reader.result).split(',')[1] ?? null);
		reader.readAsDataURL(file);
	}

	async function run(event: SubmitEvent) {
		event.preventDefault();
		if (!selected) return;
		running = true;
		runError = '';
		result = null;
		try {
			result = await runPrompt(selected.area, selected.version, { variables, tier, image_base64: image });
		} catch (e) {
			runError = describe(e);
		} finally {
			running = false;
		}
	}
</script>

<div class="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
	{#if error}<Notice tone="error" class="lg:col-span-2">{error}</Notice>{/if}
	<nav aria-label="Prompts">
		{#each groups as g (g.area + g.name)}
			<div class="mb-2">
				<p class="text-muted-foreground m-0 text-[11px] tracking-wide uppercase">{g.area}</p>
				<ul class="m-0 list-none p-0">
					{#each g.versions as v (v.version)}
						<li>
							<button
								type="button"
								class="hover:bg-muted flex w-full cursor-pointer items-center gap-1.5 rounded border-0 bg-transparent px-2 py-0.5 text-left font-mono text-xs {selected?.version === v.version && selected?.area === v.area ? 'bg-muted font-semibold' : ''}"
								aria-current={selected?.version === v.version && selected?.area === v.area ? 'true' : undefined}
								onclick={() => open(v)}
							>
								{v.version}
								{#if v.in_use}<ToneBadge tone="ok">in use</ToneBadge>{:else if v.latest}<ToneBadge tone="info">latest</ToneBadge>{/if}
							</button>
						</li>
					{/each}
				</ul>
			</div>
		{/each}
	</nav>

	<div class="grid min-w-0 content-start gap-4">
		{#if !selected}
			<p class="text-muted-foreground m-0 text-sm">Pick a prompt version. Prompts are files in the repository; a change is a new version file, and the code pins the version it uses.</p>
		{:else}
			<header class="flex flex-wrap items-center gap-2">
				<h3 class="m-0 font-mono text-sm">{selected.area} / {selected.version}</h3>
				{#if selected.in_use}<ToneBadge tone="ok">in use</ToneBadge>{/if}
				<span class="text-muted-foreground text-xs">{selected.chars} characters · variables {selected.variables.join(', ') || 'none'}</span>
			</header>
			{#if text}
				<section aria-label="Prompt text" class="grid gap-2">
					<h4 class="eyebrow m-0">System</h4>
					<pre class="code-block m-0 max-h-72 overflow-auto text-xs whitespace-pre-wrap">{text.system}</pre>
					<h4 class="eyebrow m-0">User template</h4>
					<pre class="code-block m-0 max-h-72 overflow-auto text-xs whitespace-pre-wrap">{text.user_template}</pre>
				</section>
			{/if}

			{#if siblings.length > 1}
				<section aria-label="Compare versions" class="grid gap-2">
					<label class="field-label flex items-center gap-2"
						>Compare with
						<select class="field w-48" value={compareTo} onchange={(e) => compare((e.currentTarget as HTMLSelectElement).value)}>
							<option value="">choose…</option>
							{#each siblings.filter((v) => v.version !== selected?.version) as v (v.version)}<option value={v.version}>{v.version}</option>{/each}
						</select>
					</label>
					{#if diff}
						<div class="overflow-x-auto rounded-md border">
							<table class="w-full font-mono text-xs" aria-label="Diff {compareTo} → {selected.version}">
								<thead><tr class="bg-muted/60"><th class="w-1/2 px-2 py-1 text-left">{compareTo}</th><th class="px-2 py-1 text-left">{selected.version}</th></tr></thead>
								<tbody>
									{#each diff as row, i (i)}
										<tr class="border-t align-top" data-kind={row.kind}>
											<td class="px-2 py-0.5 whitespace-pre-wrap {row.kind === 'removed' || row.kind === 'changed' ? 'bg-hard-bg' : ''}">{row.left ?? ''}</td>
											<td class="px-2 py-0.5 whitespace-pre-wrap {row.kind === 'added' || row.kind === 'changed' ? 'bg-ok-bg' : ''}">{row.right ?? ''}</td>
										</tr>
									{:else}<tr><td colspan="2" class="text-muted-foreground px-2 py-1">The two versions are identical.</td></tr>{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</section>
			{/if}

			<form class="panel grid gap-2 p-3" aria-label="Run on sample" onsubmit={run}>
				<h4 class="eyebrow m-0">Run on sample</h4>
				<p class="text-muted-foreground m-0 text-xs">One real call to the configured model; it costs tokens.</p>
				{#each selected.variables as v (v)}
					<label class="field-label grid gap-1"
						>{v}
						<textarea class="field text-foreground font-mono text-xs" rows="2" bind:value={variables[v]}></textarea>
					</label>
				{/each}
				<div class="flex flex-wrap items-end gap-3">
					<label class="field-label grid gap-1"
						>Model tier
						<select class="field w-32" bind:value={tier}><option value="flash">flash</option><option value="lite">lite</option></select>
					</label>
					<label class="field-label grid gap-1"
						>Image (vision prompts)
						<input type="file" accept="image/png,image/jpeg" class="text-xs" onchange={pickImage} />
					</label>
					<Button type="submit" size="sm" disabled={running}>{running ? 'Running…' : 'Run'}</Button>
				</div>
				{#if runError}<Notice tone="error">{runError}</Notice>{/if}
				{#if result}
					<section aria-label="Run result" class="grid gap-1">
						<p class="text-muted-foreground m-0 text-xs">
							{result.model} · {result.latency_ms} ms · tokens in {result.input_tokens ?? '—'} / out {result.output_tokens ?? '—'}
						</p>
						<pre class="code-block m-0 max-h-80 overflow-auto text-xs whitespace-pre-wrap">{result.text}</pre>
					</section>
				{/if}
			</form>
		{/if}
	</div>
</div>
