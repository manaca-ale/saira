import api from './api';

export interface User {
  id: number;
  name: string;
  email: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
  is_active: boolean;
  last_login_at?: string | null;
  // Senha definida pelo administrador: o dono troca no primeiro login.
  must_change_password?: boolean;
  // Ainda não criou a senha pelo link do convite.
  invite_pending?: boolean;
  // Só nas respostas de criar e de convidar: false = o e-mail falhou.
  invite_email_sent?: boolean | null;
}

export interface CreateUserData {
  name: string;
  email: string;
  // Sem senha (o normal): o usuário recebe o convite por e-mail.
  password?: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
  is_active?: boolean;
}

function addStatusField(user: User): User & { status: string } {
  return { ...user, status: user.is_active ? 'Ativo' : 'Inativo' };
}

export async function getUsers(params?: { skip?: number; limit?: number }): Promise<(User & { status: string })[]> {
  const response = await api.get('/users/', { params });
  return response.data.map(addStatusField);
}

export const createUser = (data: CreateUserData) => api.post<User>('/users/', data).then(r => r.data);
export const updateUser = (id: number, data: Partial<CreateUserData>) => api.patch<User>(`/users/${id}`, data).then(r => r.data);
export const deleteUser = (id: number) => api.delete(`/users/${id}`);
// (Re)envia o convite: a senha atual deixa de valer e o link anterior cai.
export const sendInvite = (id: number) => api.post<User>(`/users/${id}/invite`).then(r => r.data);
