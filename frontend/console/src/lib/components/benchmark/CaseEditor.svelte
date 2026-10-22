<script lang="ts">
	import { BEHAVIORS, CATEGORIES, emptyAnchor, emptyCitation, emptyNumeric, problems, type CaseForm } from './case_form';
	import { viewerHref } from './links';
	import XIcon from '@lucide/svelte/icons/x';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import { Button } from '$lib/components/ui/button';

	interface Props {
		form: CaseForm;
		/** shown only for a new case */
		caseId?: string | null;
		busy: boolean;
		submitLabel: string;
		onSubmit: () => void;
		onCaseId?: (value: string) => void;
	}

	let { form = $bindable(), caseId = null, busy, submitLabel, onSubmit, onCaseId }: Props = $props();
	let issues = $derived(problems(form));
</script>

{#snippet remove(label: string, onclick: () => void)}
	<Button variant="ghost" size="icon-sm" aria-label={label} title={label} class="text-muted-foreground" {onclick}><XIcon /></Button>
{/snippet}

<form
	class="grid gap-4"
	aria-label="Benchmark case"
	onsubmit={(e) => {
		e.preventDefault();
		if (!issues.length) onSubmit();
	}}
>
	<fieldset class="panel m-0 grid min-w-0 gap-3 p-4">
		<legend class="float-left mb-1 w-full p-0 text-sm font-semibold">Case</legend>
		{#if caseId !== null}
			<label class="grid gap-1"
				><span class="field-label">Case id</span>
				<input class="field font-mono" value={caseId} oninput={(e) => onCaseId?.((e.currentTarget as HTMLInputElement).value)} placeholder="tp07-t04-peak" /></label
			>
		{/if}
		<div class="grid grid-cols-[minmax(0,2fr)_minmax(0,2fr)_6rem_6rem] gap-3">
			<label class="grid gap-1"><span class="field-label">Suite</span> <input class="field" bind:value={form.suite} /></label>
			<label class="grid gap-1"
				><span class="field-label">Category</span>
				<select class="field" bind:value={form.category}>{#each CATEGORIES as c (c)}<option value={c}>{c}</option>{/each}</select>
			</label>
			<label class="grid gap-1"><span class="field-label">Difficulty</span> <input class="field" bind:value={form.difficulty} placeholder="1–5" /></label>
			<label class="grid gap-1"><span class="field-label">Language</span> <input class="field" bind:value={form.language} /></label>
		</div>
		<label class="grid gap-1"><span class="field-label">Question</span> <textarea class="field" rows="2" bind:value={form.question}></textarea></label>
		<label class="grid gap-1"
			><span class="field-label">Paraphrases (one per line)</span> <textarea class="field" rows="2" bind:value={form.paraphrases}></textarea></label
		>
	</fieldset>

	<fieldset class="panel m-0 grid min-w-0 gap-2 p-4">
		<legend class="float-left mb-1 w-full p-0 text-sm font-semibold">Expected numbers</legend>
		{#each form.numeric as row, i (i)}
			<div class="grid grid-cols-[minmax(0,1fr)_7rem_6rem_auto_auto] items-center gap-2">
				<input class="field" aria-label="Metric {i + 1}" placeholder="metric" bind:value={row.metric} />
				<input class="field num font-mono" aria-label="Value {i + 1}" placeholder="value" bind:value={row.value} />
				<input class="field" aria-label="Unit {i + 1}" placeholder="unit" bind:value={row.unit} />
				<label class="text-muted-foreground flex items-center gap-1 text-xs"
					>± <input class="field num w-16 font-mono" aria-label="Tolerance {i + 1}" bind:value={row.tolerance_pct} /> %</label
				>
				{@render remove(`Remove number ${i + 1}`, () => form.numeric.splice(i, 1))}
			</div>
		{/each}
		<div><Button variant="outline" size="sm" onclick={() => form.numeric.push(emptyNumeric())}><PlusIcon />Add number</Button></div>
	</fieldset>

	{#each [{ key: 'citations', title: 'Expected citations' }, { key: 'mustNotCite', title: 'Must not cite' }] as const as group (group.key)}
		<fieldset class="panel m-0 grid min-w-0 gap-2 p-4">
			<legend class="float-left mb-1 w-full p-0 text-sm font-semibold">{group.title}</legend>
			{#each form[group.key] as row, i (i)}
				<div class="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_5rem_auto] items-center gap-2">
					<input class="field" aria-label="{group.title} file {i + 1}" placeholder="file name" bind:value={row.file_name} />
					<input class="field font-mono" aria-label="{group.title} doc {i + 1}" placeholder="doc id" bind:value={row.doc_id} />
					<input class="field" aria-label="{group.title} standard {i + 1}" placeholder="standard id" bind:value={row.standard_id} />
					<input class="field num font-mono" aria-label="{group.title} page {i + 1}" placeholder="page" bind:value={row.page} />
					{@render remove(`Remove ${group.title} ${i + 1}`, () => form[group.key].splice(i, 1))}
				</div>
			{/each}
			<div><Button variant="outline" size="sm" onclick={() => form[group.key].push(emptyCitation())}><PlusIcon />Add</Button></div>
		</fieldset>
	{/each}

	<fieldset class="panel m-0 grid min-w-0 gap-3 p-4">
		<legend class="float-left mb-1 w-full p-0 text-sm font-semibold">Tools and entities</legend>
		<div class="flex items-end gap-3">
			<label class="grid flex-1 gap-1"
				><span class="field-label">Expected tools</span> <input class="field font-mono" bind:value={form.tools} placeholder="query_telemetry, search_documents" /></label
			>
			<label class="flex h-8 items-center gap-2"><input type="checkbox" bind:checked={form.toolsOrdered} /> in this order</label>
		</div>
		<label class="grid gap-1"><span class="field-label">Expected entities</span> <input class="field" bind:value={form.entities} placeholder="C-103, TP37" /></label>
	</fieldset>

	<fieldset class="panel m-0 grid min-w-0 gap-2 p-4">
		<legend class="float-left mb-1 w-full p-0 text-sm font-semibold">Gold passages (retrieval)</legend>
		{#each form.anchors as row, i (i)}
			<div class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_3rem_auto] items-center gap-2">
				<input class="field font-mono" aria-label="Gold doc {i + 1}" placeholder="doc id" bind:value={row.doc_id} />
				<input class="field font-mono" aria-label="Gold anchor {i + 1}" placeholder="page:8:3f2a9c1b7d4e5f60" bind:value={row.anchor} />
				<span class="text-xs">{#if row.doc_id && row.anchor}<a href={viewerHref(row.doc_id, row.anchor)} target="_blank" rel="noopener">open</a>{/if}</span>
				{@render remove(`Remove gold ${i + 1}`, () => form.anchors.splice(i, 1))}
			</div>
		{/each}
		<div><Button variant="outline" size="sm" onclick={() => form.anchors.push(emptyAnchor())}><PlusIcon />Add passage</Button></div>
	</fieldset>

	<fieldset class="panel m-0 grid min-w-0 gap-3 p-4">
		<legend class="float-left mb-1 w-full p-0 text-sm font-semibold">Expected behavior</legend>
		<div class="grid gap-1.5 sm:grid-cols-2">
			{#each BEHAVIORS as b (b.value)}
				<label class="flex items-center gap-2"><input type="checkbox" bind:group={form.behaviors} value={b.value} /> {b.label}</label>
			{/each}
		</div>
		<label class="grid gap-1"
			><span class="field-label">Clarification answer (used when the engine asks back)</span> <input class="field" bind:value={form.clarification} /></label
		>
		<label class="grid gap-1"><span class="field-label">Notes</span> <textarea class="field" rows="2" bind:value={form.notes}></textarea></label>
	</fieldset>

	<div class="bg-background/90 sticky bottom-0 -mx-1 flex items-start justify-between gap-4 border-t px-1 py-3 backdrop-blur">
		{#if issues.length}
			<ul class="text-warn m-0 list-disc space-y-0.5 pl-5 text-sm" role="alert">{#each issues as issue (issue)}<li>{issue}</li>{/each}</ul>
		{:else}
			<span class="text-muted-foreground text-sm">Ready to save.</span>
		{/if}
		<Button type="submit" disabled={busy || issues.length > 0}>{submitLabel}</Button>
	</div>
</form>
