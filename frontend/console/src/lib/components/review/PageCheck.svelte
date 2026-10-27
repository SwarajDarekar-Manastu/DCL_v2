<script lang="ts">
	// The page check (phase 1c): a page read whole, its image beside everything the reader made of it. Tables are
	// grids, crossed-out text is struck through, and each entry the reader was unsure of is highlighted where it
	// sits and answered in "To check": confirm, correct (type, or pick an alternative), or unreadable. Any other
	// cell or line can be corrected too (click, type, Enter): a set_cell / set_text kept beside the answers.
	// Model text is only ever rendered as text, never as HTML.
	import { tick, untrack } from 'svelte';
	import type { FlagView, PageEntry, PageReading, Resolution } from '$lib/api_endpoint';
	import AssetImage from './AssetImage.svelte';
	import ImageZoom from './ImageZoom.svelte';
	import { entryState, placeKey, segments, spans, STATE_MARK } from './page_check';

	interface Props {
		reading: PageReading;
		flags: FlagView[];
		drafts: Record<string, Resolution | null>;
	}

	let { reading, flags, drafts = $bindable() }: Props = $props();
	const OPEN = ['OPEN', 'IN_PROGRESS', 'REOPENED'];

	let openIds = $derived(new Set(flags.filter((f) => OPEN.includes(f.status)).map((f) => f.flag_id)));
	let entries = $derived(reading.entries.filter((e): e is PageEntry & { flag_id: string } => !!e.flag_id && openIds.has(e.flag_id)));
	let byPlace = $derived(new Map(entries.flatMap((e) => (placeKey(e.located) ? [[placeKey(e.located)!, e] as const] : []))));
	let done = $derived(entries.filter((e) => entryState(e, drafts[e.flag_id]) !== 'to check').length);

	// The field of each entry: its draft's value, else what the reader read.
	let values = $state<Record<string, string>>({});
	$effect(() => {
		for (const e of entries) {
			if (untrack(() => e.flag_id in values)) continue;
			const draft = untrack(() => drafts[e.flag_id]);
			values[e.flag_id] = draft?.action === 'set_value' && !draft.illegible ? (draft.value ?? '') : (e.value ?? '');
		}
	});

	function answer(entry: PageEntry & { flag_id: string }, illegible = false) {
		drafts[entry.flag_id] = illegible
			? { action: 'set_value', value: null, unit: entry.unit ?? null, illegible: true }
			: { action: 'set_value', value: values[entry.flag_id], unit: entry.unit ?? null, illegible: false };
	}

	let list = $state<HTMLElement | null>(null);
	async function next(after: string) {
		await tick(); // Apply is enabled only once the last answer has rendered
		const fields = [...(list?.querySelectorAll<HTMLInputElement>('input[data-entry]') ?? [])];
		const start = fields.findIndex((f) => f.dataset.entry === after);
		const open = fields.slice(start + 1).find((f) => entryState({ value: f.dataset.read ?? '' }, drafts[f.dataset.entry!]) === 'to check');
		(open ?? document.querySelector<HTMLElement>('[data-apply]'))?.focus();
	}

	function onKey(event: KeyboardEvent, entry: PageEntry & { flag_id: string }) {
		if (event.key === 'Enter') {
			event.preventDefault();
			answer(entry);
			next(entry.flag_id);
		} else if (event.key === 'Escape') {
			event.preventDefault();
			values[entry.flag_id] = entry.value ?? '';
			drafts[entry.flag_id] = null;
		}
	}

	function focusEntry(entry: PageEntry) {
		list?.querySelector<HTMLInputElement>(`input[data-entry="${entry.flag_id}"]`)?.focus();
	}

	let zoomed = $state<string | null>(null);
	let opener: HTMLElement | null = null;
	const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)} %`);
	const cellKey = (block: string, t: number, r: number, c: number) => `table:${block}:${t}:${r}:${c}`;

	// Corrections of what the reader did not flag: drafts keyed "cell:…" / "text:…" (drafts.ts isCorrection).
	let editing = $state<string | null>(null);
	let changes = $derived(Object.entries(drafts).filter(([k, r]) => r && (k.startsWith('cell:') || k.startsWith('text:'))).length);
	const focusOnMount = (node: HTMLInputElement) => {
		node.focus();
		node.select();
	};
	type Fix = { action: 'set_cell'; block_key: string; table: number; row: number; col: number; old: string; value: string } | { action: 'set_text'; block_key: string; old: string; text: string };
	function shownFix(key: string): string | null {
		const fix = drafts[key];
		return fix?.action === 'set_cell' ? fix.value : fix?.action === 'set_text' ? fix.text : null;
	}
	// Enter or leaving the field keeps what was typed (as in a spreadsheet); Escape leaves the text as it was.
	function keep(key: string, fix: Fix, typed: string) {
		if (editing !== key) return;
		if (typed === fix.old) delete drafts[key]; // back to the text as read: no correction
		else drafts[key] = fix.action === 'set_cell' ? { ...fix, value: typed } : { ...fix, text: typed };
		editing = null;
	}
	function onEditKey(event: KeyboardEvent, key: string, fix: Fix) {
		if (event.key === 'Escape') {
			event.preventDefault();
			editing = null;
		} else if (event.key === 'Enter') {
			event.preventDefault();
			keep(key, fix, (event.currentTarget as HTMLInputElement).value);
		}
	}
</script>

<section class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]" aria-label="Page check">
	<div class="self-start xl:sticky xl:top-2">
		{#if reading.image_uri}
			<button
				type="button"
				class="w-full cursor-zoom-in rounded-md border bg-transparent p-1"
				aria-label="Zoom page {reading.page_no}"
				onclick={(e) => {
					opener = e.currentTarget;
					zoomed = reading.image_uri ?? null;
				}}
			>
				<AssetImage uri={reading.image_uri} alt="Page {reading.page_no}" class="mx-auto max-h-[78vh] w-full rounded bg-white object-contain" />
			</button>
		{/if}
	</div>

	<div class="grid content-start gap-4">
		<header class="grid gap-1">
			<h3 class="m-0 text-base font-semibold">Page {reading.page_no} as read</h3>
			<p class="text-muted-foreground m-0 text-[13px]" role="status">
				{entries.length} {entries.length === 1 ? 'entry' : 'entries'} to check · {done} of {entries.length} done{changes
					? ` · ${changes} ${changes === 1 ? 'correction' : 'corrections'} to save`
					: ''}
			</p>
			<p class="text-muted-foreground m-0 text-xs">Something else read wrong? Click it, type the right text, press Enter.</p>
		</header>

		{#if entries.length}
			<ul class="m-0 grid list-none gap-2 p-0" aria-label="To check" bind:this={list}>
				{#each entries as entry (entry.flag_id)}
					{@const state = entryState(entry, drafts[entry.flag_id])}
					<li class="grid gap-1.5 rounded-md border p-2.5 {state === 'to check' ? 'border-warn' : ''}">
						<div class="flex flex-wrap items-center gap-2 text-[13px]">
							<span class="text-xs {state === 'to check' ? 'text-warn' : 'text-muted-foreground'}">{STATE_MARK[state]} {state}</span>
							<span class="font-medium">{entry.label ?? 'Entry'}</span>
							<span class="ml-auto flex gap-2">
								<button type="button" class="rounded-md border px-2.5 py-1 text-xs" disabled={entry.illegible && !values[entry.flag_id]} onclick={() => answer(entry)}>Confirm</button>
								<button type="button" class="rounded-md border px-2.5 py-1 text-xs" onclick={() => answer(entry, true)}>Unreadable</button>
							</span>
						</div>
						<input
							class="field h-8 w-full font-mono"
							aria-label={entry.label ?? 'Entry'}
							spellcheck="false"
							autocomplete="off"
							data-resolution
							data-entry={entry.flag_id}
							data-read={entry.value ?? ''}
							disabled={state === 'unreadable'}
							bind:value={values[entry.flag_id]}
							onkeydown={(e) => onKey(e, entry)}
						/>
						<p class="text-muted-foreground m-0 text-xs">
							Read as <span class="text-foreground font-mono">“{entry.value ?? '[illegible]'}”</span> · confidence {pct(entry.confidence)}{entry.located
								? ''
								: ' · not found in the text below'}
						</p>
						{#if entry.alternatives.length}
							<div class="flex flex-wrap gap-1.5" aria-label="Alternatives for {entry.label ?? 'this entry'}">
								{#each entry.alternatives as alt (alt)}
									<button
										type="button"
										class="bg-muted hover:bg-accent rounded-full border px-2 py-0.5 font-mono text-xs"
										onclick={() => {
											values[entry.flag_id] = alt;
											answer(entry);
										}}>{alt}</button
									>
								{/each}
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}

		<article class="grid gap-3 rounded-md border p-3 text-[13px]" aria-label="Page {reading.page_no} text">
			{#each reading.blocks as block (block.key)}
				{@const inText = byPlace.get(`text:${block.key}`)}
				<div class="grid gap-2 {inText ? 'border-warn border-l-2 pl-2' : ''}">
					{#each block.parts as part, p (p)}
						{#if part.kind === 'heading' || part.kind === 'text'}
							{#each (part.text ?? '').split('\n') as line, l (l)}
								{@const key = `text:${block.key}:${line}`}
								{@const fixed = shownFix(key)}
								{#if editing === key}
									<input
										class="field h-8 w-full text-[13px]"
										aria-label="Correct line"
										spellcheck="false"
										value={fixed ?? line}
										use:focusOnMount
										onkeydown={(e) => onEditKey(e, key, { action: 'set_text', block_key: block.key, old: line, text: line })}
										onblur={(e) => keep(key, { action: 'set_text', block_key: block.key, old: line, text: line }, e.currentTarget.value)}
									/>
								{:else}
									<button
										type="button"
										class="hover:bg-muted m-0 block w-full cursor-text rounded border-0 bg-transparent p-0 text-left whitespace-pre-line {part.kind === 'heading' ? 'text-sm font-semibold' : ''}"
										aria-label="{part.kind === 'heading' ? 'Heading' : 'Line'}: {fixed ?? line}"
										onclick={() => (editing = key)}
										>{#if fixed !== null}{fixed} <span aria-hidden="true">✎</span>{:else}{#each segments(line, part.struck) as piece, i (i)}{#if piece.struck}<s>{piece.text}</s>{:else}{piece.text}{/if}{/each}{#if part.corrected.includes(line)}
												<span aria-hidden="true">✎</span>{/if}{/if}</button
									>
								{/if}
							{/each}
						{:else if part.rows}
							{@const t = block.parts.slice(0, p).filter((x) => x.kind === 'table').length}
							{@const span = spans(part.rows)}
							<div class="overflow-x-auto">
								<table class="w-full border-collapse text-xs">
									<tbody>
										{#each part.rows as row, r (r)}
											<tr>
												{#each row as cell, c (c)}
													{#if !cell.span_of}
														{@const entry = byPlace.get(cellKey(block.key, t, r, c))}
														{@const s = span.get(`${r}:${c}`)}
														{#if entry}
															{@const state = entryState(entry, drafts[entry.flag_id])}
															<td
																rowspan={s?.rowspan}
																colspan={s?.colspan}
																class="cursor-pointer border px-1.5 py-0.5 font-mono whitespace-pre-line {state === 'to check' ? 'bg-warn-bg text-warn' : 'bg-muted'}"
																aria-label="Unsure entry: {entry.label ?? 'entry'}"
																onclick={() => focusEntry(entry)}
																>{state === 'unreadable' ? '[illegible]' : values[entry.flag_id] ?? cell.text} <span aria-hidden="true">{STATE_MARK[state]}</span></td
															>
														{:else}
															{@const key = `cell:${block.key}:${t}:${r}:${c}`}
															{@const fixed = shownFix(key)}
															<td
																rowspan={s?.rowspan}
																colspan={s?.colspan}
																class="hover:bg-muted cursor-text border px-1.5 py-0.5 whitespace-pre-line {fixed !== null || cell.corrected ? 'bg-muted' : ''}"
																aria-label={fixed !== null || cell.corrected ? `Corrected: ${fixed ?? cell.text}` : undefined}
																onclick={() => (editing = key)}
															>
																{#if editing === key}
																	<input
																		class="field h-7 w-full min-w-24 text-xs"
																		aria-label="Correct cell"
																		spellcheck="false"
																		value={fixed ?? cell.text}
																		use:focusOnMount
																		onkeydown={(e) =>
																			onEditKey(e, key, { action: 'set_cell', block_key: block.key, table: t, row: r, col: c, old: cell.text, value: cell.text })}
																		onblur={(e) =>
																			keep(key, { action: 'set_cell', block_key: block.key, table: t, row: r, col: c, old: cell.text, value: cell.text }, e.currentTarget.value)}
																	/>
																{:else if fixed !== null}{fixed} <span aria-hidden="true">✎</span>{:else}{#each segments(cell.text, cell.struck) as piece, i (i)}{#if piece.struck}<s>{piece.text}</s>{:else}{piece.text}{/if}{/each}{#if cell.corrected}
																		<span aria-hidden="true">✎</span>{/if}{/if}
															</td>
														{/if}
													{/if}
												{/each}
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}
					{/each}
				</div>
			{/each}
		</article>
	</div>
</section>

<ImageZoom
	uri={zoomed}
	onClose={() => {
		zoomed = null;
		opener?.focus();
	}}
/>
