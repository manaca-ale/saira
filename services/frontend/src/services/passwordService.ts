import api from './api';

// Fluxos de senha (docs/specs/acesso-usuarios.md). As rotas públicas
// respondem 400 com `detail` = token_invalid | token_expired | token_used.

export interface PasswordTokenInfo {
  purpose: 'invite' | 'reset';
  name: string;
  email: string;
  expires_at: string;
}

export const TOKEN_ERRORS: Record<string, string> = {
  token_invalid: 'Este link não é válido. Ele pode ter sido substituído por um mais novo ou copiado pela metade.',
  token_expired: 'Este link venceu. Peça um novo ao administrador ou use "Esqueceu a senha?" na tela de login.',
  token_used: 'Este link já foi usado. Se você já criou a sua senha, é só entrar.',
};

export function errorDetail(error: unknown): unknown {
  return (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
}

export function errorMessage(error: unknown, fallback: string): string {
  const detail = errorDetail(error);
  if (typeof detail === 'string') return TOKEN_ERRORS[detail] || detail;
  if (Array.isArray(detail)) {
    // Validação do FastAPI (422): o caso comum é a senha curta ou longa demais.
    const loc = JSON.stringify(detail[0]?.loc || '');
    if (loc.includes('password')) return 'A senha precisa ter entre 8 e 128 caracteres.';
  }
  return fallback;
}

export const requestPasswordReset = (email: string) =>
  api.post<{ message: string }>('/auth/password/forgot', { email }).then((r) => r.data);

export const getPasswordTokenInfo = (token: string) =>
  api.post<PasswordTokenInfo>('/auth/password/token', { token }).then((r) => r.data);

export const setPasswordWithToken = (token: string, password: string) =>
  api.post<{ message: string; email?: string }>('/auth/password/set', { token, password }).then((r) => r.data);

export const changePassword = (current_password: string, new_password: string) =>
  api
    .post<{ access_token: string; token_type: string }>('/auth/password/change', { current_password, new_password })
    .then((r) => r.data);
