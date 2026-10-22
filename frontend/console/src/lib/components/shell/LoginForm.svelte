<script lang="ts">
	// Local sign-in form: email and password. Errors from the API (wrong password, too many attempts) show inline.
	import { ApiError } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from './Notice.svelte';

	interface Props {
		onSubmit: (email: string, password: string) => Promise<void>;
		notice?: string;
	}

	let { onSubmit, notice = '' }: Props = $props();
	let email = $state('');
	let password = $state('');
	let busy = $state(false);
	let error = $state('');

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = '';
		try {
			await onSubmit(email.trim(), password);
			password = '';
		} catch (e) {
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<form class="mt-6 grid gap-3 text-left" aria-label="Sign in" onsubmit={submit}>
	{#if notice && !error}<Notice tone="info">{notice}</Notice>{/if}
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	<label class="field-label grid gap-1"
		>Email
		<input class="field text-foreground" type="email" name="email" autocomplete="username" required bind:value={email} />
	</label>
	<label class="field-label grid gap-1"
		>Password
		<input class="field text-foreground" type="password" name="password" autocomplete="current-password" required bind:value={password} />
	</label>
	<Button type="submit" class="mt-2 w-full" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
</form>
