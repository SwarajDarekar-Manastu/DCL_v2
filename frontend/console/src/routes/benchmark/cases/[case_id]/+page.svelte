<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		addCaseVersion,
		ApiError,
		approveCase,
		caseHistory,
		createBenchmarkCase,
		retireCase,
		startRun,
		type BenchmarkCase
	} from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import CaseEditor from '$lib/components/benchmark/CaseEditor.svelte';
	import { emptyForm, formFromCase, toContent, type CaseForm } from '$lib/components/benchmark/case_form';
	import { caseHref, runHref, suiteHref } from '$lib/components/benchmark/links';
	import { runRequest } from '$lib/components/benchmark/run_view';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';

	let caseId = $derived(page.params.case_id ?? '');
	let isNew = $derived(caseId === 'new');
	let history = $state<BenchmarkCase[]>([]);
	let form = $state<CaseForm>(emptyForm());
	let newId = $state('');
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let canEdit = $derived(hasRole(session.user?.roles ?? [], 'reviewer'));
	let latest = $derived(history[0] ?? null);

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	$effect(() => {
		const id = caseId;
		error = '';
		notice = '';
		if (id === 'new') {
			history = [];
			form = emptyForm(page.url.searchParams.get('suite') ?? '');
			return;
		}
		caseHistory(id)
			.then((versions) => {
				history = versions;
				form = formFromCase(versions[0]);
			})
			.catch((e) => (error = describe(e)));
	});

	async function act(action: () => Promise<BenchmarkCase>, message: string) {
		busy = true;
		error = '';
		try {
			const saved = await action();
			notice = message.replace('{v}', String(saved.version));
			if (isNew) await goto(caseHref(saved.case_id));
			else {
				history = await caseHistory(saved.case_id);
				form = formFromCase(history[0]);
			}
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	async function runNow(suite: string) {
		busy = true;
		error = '';
		try {
			const created = await startRun(runRequest(suite, [caseId]));
			await goto(runHref(created.run_id));
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	const save = () =>
		isNew
			? act(() => createBenchmarkCase({ ...toContent(form), case_id: newId.trim(), status: 'active' }), 'Case created.')
			: act(() => addCaseVersion(caseId, toContent(form)), 'Saved as version {v}.');
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<nav class="crumbs"><a href="/benchmark">Benchmark</a> › {#if form.suite}<a href={suiteHref(form.suite)}>{form.suite}</a> ›{/if} {isNew ? 'New case' : caseId}</nav>
	{#if latest}
		<p class="status">
			Version {latest.version} · <strong>{latest.status}</strong> · by {latest.created_by} · {latest.created_at.slice(0, 10)}
			{#if latest.source_trace_id}· from chat trace <code>{latest.source_trace_id}</code>{/if}
			{#if canEdit && latest.status === 'draft'}<button type="button" disabled={busy} onclick={() => act(() => approveCase(caseId), 'Approved.')}>Approve draft</button>{/if}
			{#if canEdit && latest.status === 'active'}<button type="button" disabled={busy} onclick={() => runNow(latest.suite)}>Run this case now</button>{/if}
			{#if canEdit && latest.status !== 'retired'}<button type="button" disabled={busy} onclick={() => act(() => retireCase(caseId), 'Retired.')}>Retire</button>{/if}
		</p>
	{/if}
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	{#if notice}<p class="notice" role="status">{notice}</p>{/if}

	{#if canEdit}
		<CaseEditor
			bind:form
			caseId={isNew ? newId : null}
			onCaseId={(v) => (newId = v)}
			{busy}
			submitLabel={isNew ? 'Create case' : 'Save as new version'}
			onSubmit={save}
		/>
	{:else if latest}
		<pre>{JSON.stringify(latest, null, 2)}</pre>
	{/if}

	{#if history.length > 1}
		<h2>History</h2>
		<ol class="history">
			{#each history as v (v.version)}
				<li>v{v.version} · {v.status} · {v.created_by} · {v.created_at.slice(0, 16).replace('T', ' ')} · {v.question}</li>
			{/each}
		</ol>
	{/if}
</RoleGate>

<style>
	.crumbs,
	.status {
		font-size: 0.85rem;
	}
	.status button {
		margin-left: 0.5rem;
		font: inherit;
		font-size: 0.8rem;
		padding: 0.15rem 0.6rem;
		cursor: pointer;
	}
	.error {
		color: var(--hard);
	}
	.notice {
		color: var(--ok);
	}
	h2 {
		font-size: 1rem;
	}
	.history {
		font-size: 0.82rem;
	}
</style>
