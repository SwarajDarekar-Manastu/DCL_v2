<script lang="ts">
	// Every version of one key, newest first; an older version can be restored (written as a new version).
	import { ApiError, rollbackSettings, settingHistory, type ConfigEntry } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { summary } from './settings_form';

	interface Props {
		key: string;
		onRestored: (message: string) => void;
	}

	let { key, onRestored }: Props = $props();
	let versions = $state<ConfigEntry[]>([]);
	let error = $state('');
	let busy = $state(false);

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	$effect(() => {
		settingHistory(key)
			.then((h) => (versions = h.items))
			.catch((e) => (error = describe(e)));
	});

	async function restore(v: ConfigEntry) {
		busy = true;
		error = '';
		try {
			const result = await rollbackSettings({ versions: { [key]: v.version }, description: `restore version ${v.version}` });
			onRestored(`${key} restored to version ${v.version} (now version ${result.applied[0]?.version ?? '?'}).`);
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="mt-2 grid gap-2">
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	<ol class="m-0 grid gap-1 p-0" aria-label="History of {key}">
		{#each versions as v, i (v.version)}
			<li class="flex list-none items-start gap-3 rounded-md border px-3 py-2 text-xs">
				<span class="num w-8 shrink-0 font-mono">v{v.version}</span>
				<span class="min-w-0 flex-1">
					<code class="block break-all">{summary(v.value)}</code>
					<span class="text-muted-foreground">{v.updated_by} · {v.updated_at.slice(0, 16).replace('T', ' ')}{v.description ? ` · ${v.description}` : ''}</span>
				</span>
				{#if i === 0}<span class="text-muted-foreground">current</span>{:else}<Button variant="outline" size="xs" disabled={busy} onclick={() => restore(v)}>Restore</Button>{/if}
			</li>
		{/each}
	</ol>
</div>
