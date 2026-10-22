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
		type BenchmarkCase
	} from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import CaseEditor from '$lib/components/benchmark/CaseEditor.svelte';
	import { emptyForm, formFromCase, toContent, type CaseForm } from '$lib/components/benchmark/case_form';
	import { caseHref, suiteHref } from '$lib/components/benchmark/links';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';

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

	const statusTone = (status: string) => (status === 'active' ? 'ok' : status === 'draft' ? 'warn' : 'neutral');
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

	const save = () =>
		isNew
			? act(() => createBenchmarkCase({ ...toContent(form), case_id: newId.trim(), status: 'active' }), 'Case created.')
			: act(() => addCaseVersion(caseId, toContent(form)), 'Saved as version {v}.');
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<Page title={isNew ? 'New case' : caseId} width="narrow">
		{#snippet actions()}
			{#if form.suite}<Button variant="outline" size="sm" href={suiteHref(form.suite)}>Suite {form.suite}</Button>{/if}
			{#if latest && canEdit && latest.status === 'draft'}
				<Button size="sm" disabled={busy} onclick={() => act(() => approveCase(caseId), 'Approved.')}>Approve draft</Button>
			{/if}
			{#if latest && canEdit && latest.status !== 'retired'}
				<Button variant="destructive" size="sm" disabled={busy} onclick={() => act(() => retireCase(caseId), 'Retired.')}>Retire</Button>
			{/if}
		{/snippet}
		{#snippet below()}
			{#if latest}
				<p class="text-muted-foreground m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
					<span>Version <span class="num text-foreground font-mono">{latest.version}</span></span>
					<ToneBadge tone={statusTone(latest.status)}>{latest.status}</ToneBadge>
					<span>by {latest.created_by}</span>
					<span class="num">{latest.created_at.slice(0, 10)}</span>
					{#if latest.source_trace_id}<span>from chat trace <code>{latest.source_trace_id}</code></span>{/if}
				</p>
			{/if}
		{/snippet}

		{#if error}<Notice tone="error" class="mb-4">{error}</Notice>{/if}
		{#if notice}<Notice tone="success" class="mb-4">{notice}</Notice>{/if}

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
			<pre class="code-block">{JSON.stringify(latest, null, 2)}</pre>
		{/if}

		{#if history.length > 1}
			<section class="panel mt-6" aria-labelledby="history-title">
				<div class="panel-header"><h2 id="history-title" class="panel-title">History</h2></div>
				<table class="data-table" aria-label="Versions">
					<thead><tr><th>Version</th><th>Status</th><th>By</th><th>When</th><th>Question</th></tr></thead>
					<tbody>
						{#each history as v (v.version)}
							<tr>
								<td class="num font-mono">v{v.version}</td>
								<td><ToneBadge tone={statusTone(v.status)}>{v.status}</ToneBadge></td>
								<td>{v.created_by}</td>
								<td class="num text-muted-foreground whitespace-nowrap">{v.created_at.slice(0, 16).replace('T', ' ')}</td>
								<td>{v.question}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</section>
		{/if}
	</Page>
</RoleGate>
