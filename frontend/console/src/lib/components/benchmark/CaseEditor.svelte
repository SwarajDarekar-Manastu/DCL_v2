<script lang="ts">
	import { BEHAVIORS, CATEGORIES, emptyAnchor, emptyCitation, emptyNumeric, problems, type CaseForm } from './case_form';
	import { viewerHref } from './links';

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

<form
	class="editor"
	aria-label="Benchmark case"
	onsubmit={(e) => {
		e.preventDefault();
		if (!issues.length) onSubmit();
	}}
>
	<fieldset>
		<legend>Case</legend>
		{#if caseId !== null}
			<label>Case id <input value={caseId} oninput={(e) => onCaseId?.((e.currentTarget as HTMLInputElement).value)} placeholder="tp07-t04-peak" /></label>
		{/if}
		<div class="row">
			<label>Suite <input bind:value={form.suite} /></label>
			<label
				>Category
				<select bind:value={form.category}>{#each CATEGORIES as c (c)}<option value={c}>{c}</option>{/each}</select>
			</label>
			<label>Difficulty <input class="short" bind:value={form.difficulty} placeholder="1–5" /></label>
			<label>Language <input class="short" bind:value={form.language} /></label>
		</div>
		<label>Question <textarea rows="2" bind:value={form.question}></textarea></label>
		<label>Paraphrases (one per line) <textarea rows="2" bind:value={form.paraphrases}></textarea></label>
	</fieldset>

	<fieldset>
		<legend>Expected numbers</legend>
		{#each form.numeric as row, i (i)}
			<div class="row">
				<input aria-label="Metric {i + 1}" placeholder="metric" bind:value={row.metric} />
				<input aria-label="Value {i + 1}" class="short" placeholder="value" bind:value={row.value} />
				<input aria-label="Unit {i + 1}" class="short" placeholder="unit" bind:value={row.unit} />
				<label class="inline">± <input aria-label="Tolerance {i + 1}" class="short" bind:value={row.tolerance_pct} /> %</label>
				<button type="button" aria-label="Remove number {i + 1}" onclick={() => form.numeric.splice(i, 1)}>×</button>
			</div>
		{/each}
		<button type="button" onclick={() => form.numeric.push(emptyNumeric())}>Add number</button>
	</fieldset>

	{#each [{ key: 'citations', title: 'Expected citations' }, { key: 'mustNotCite', title: 'Must not cite' }] as const as group (group.key)}
		<fieldset>
			<legend>{group.title}</legend>
			{#each form[group.key] as row, i (i)}
				<div class="row">
					<input aria-label="{group.title} file {i + 1}" placeholder="file name" bind:value={row.file_name} />
					<input aria-label="{group.title} doc {i + 1}" placeholder="doc id" bind:value={row.doc_id} />
					<input aria-label="{group.title} standard {i + 1}" placeholder="standard id" bind:value={row.standard_id} />
					<input aria-label="{group.title} page {i + 1}" class="short" placeholder="page" bind:value={row.page} />
					<button type="button" aria-label="Remove {group.title} {i + 1}" onclick={() => form[group.key].splice(i, 1)}>×</button>
				</div>
			{/each}
			<button type="button" onclick={() => form[group.key].push(emptyCitation())}>Add</button>
		</fieldset>
	{/each}

	<fieldset>
		<legend>Tools and entities</legend>
		<div class="row">
			<label>Expected tools <input bind:value={form.tools} placeholder="query_telemetry, search_documents" /></label>
			<label class="inline"><input type="checkbox" bind:checked={form.toolsOrdered} /> in this order</label>
		</div>
		<label>Expected entities <input bind:value={form.entities} placeholder="C-103, TP37" /></label>
	</fieldset>

	<fieldset>
		<legend>Gold passages (retrieval)</legend>
		{#each form.anchors as row, i (i)}
			<div class="row">
				<input aria-label="Gold doc {i + 1}" placeholder="doc id" bind:value={row.doc_id} />
				<input aria-label="Gold anchor {i + 1}" placeholder="page:8:3f2a9c1b7d4e5f60" bind:value={row.anchor} />
				{#if row.doc_id && row.anchor}<a href={viewerHref(row.doc_id, row.anchor)} target="_blank" rel="noopener">open</a>{/if}
				<button type="button" aria-label="Remove gold {i + 1}" onclick={() => form.anchors.splice(i, 1)}>×</button>
			</div>
		{/each}
		<button type="button" onclick={() => form.anchors.push(emptyAnchor())}>Add passage</button>
	</fieldset>

	<fieldset>
		<legend>Expected behavior</legend>
		{#each BEHAVIORS as b (b.value)}
			<label class="inline"><input type="checkbox" bind:group={form.behaviors} value={b.value} /> {b.label}</label>
		{/each}
		<label>Clarification answer (used when the engine asks back) <input bind:value={form.clarification} /></label>
		<label>Notes <textarea rows="2" bind:value={form.notes}></textarea></label>
	</fieldset>

	{#if issues.length}
		<ul class="issues" role="alert">{#each issues as issue (issue)}<li>{issue}</li>{/each}</ul>
	{/if}
	<button type="submit" class="primary" disabled={busy || issues.length > 0}>{submitLabel}</button>
</form>

<style>
	.editor {
		display: grid;
		gap: 0.8rem;
		font-size: 0.84rem;
		max-width: 60rem;
	}
	fieldset {
		border: 1px solid var(--border);
		border-radius: 0.4rem;
		padding: 0.6rem 0.8rem;
		display: grid;
		gap: 0.45rem;
	}
	legend {
		font-weight: 600;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem 0.6rem;
		align-items: end;
	}
	label {
		display: grid;
		gap: 0.15rem;
	}
	.inline {
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	input:not([type='checkbox']),
	select,
	textarea {
		font: inherit;
		padding: 0.25rem 0.35rem;
		background: var(--surface);
		color: inherit;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
	}
	.short {
		width: 5rem;
	}
	button {
		justify-self: start;
		font: inherit;
		font-size: 0.8rem;
		padding: 0.2rem 0.6rem;
		cursor: pointer;
	}
	.primary {
		background: var(--accent);
		color: white;
		border: 0;
		border-radius: 0.3rem;
		padding: 0.4rem 1rem;
		font-size: 0.88rem;
	}
	.primary:disabled {
		opacity: 0.5;
	}
	.issues {
		color: var(--warn);
		margin: 0;
	}
</style>
