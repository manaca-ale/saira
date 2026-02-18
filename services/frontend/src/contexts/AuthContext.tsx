import { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import api from '../services/api';

interface User {
  id: number;
  name: string;
  email: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
  is_active: boolean;
}

interface SignInCredentials {
  email: string;
  password: string;
}

interface AuthContextData {
  user: User | null;
  isAuthenticated: boolean;
  loading: boolean;
  signIn: (credentials: SignInCredentials) => Promise<void>;
  signInWithConecta: (nextPath?: string) => Promise<void>;
  completeConectaLogin: (ticket: string) => Promise<void>;
  signOut: (options?: { global?: boolean }) => Promise<void>;
}

interface AuthProviderProps {
  children: ReactNode;
}

const AuthContext = createContext<AuthContextData | undefined>(undefined);

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadUserFromStorage() {
      const token = localStorage.getItem('@Saira:token');
      const storedUser = localStorage.getItem('@Saira:user');

      if (token && storedUser) {
        try {
          // Validar token e buscar dados atualizados do usuário
          const response = await api.get('/auth/me');
          setUser(response.data);
          localStorage.setItem('@Saira:user', JSON.stringify(response.data));
        } catch (error) {
          // Token inválido, limpar storage
          localStorage.removeItem('@Saira:token');
          localStorage.removeItem('@Saira:user');
        }
      }

      setLoading(false);
    }

    loadUserFromStorage();
  }, []);

  async function signIn({ email, password }: SignInCredentials) {
    try {
      // API usa OAuth2PasswordRequestForm que espera form-data com 'username'
      const formData = new URLSearchParams();
      formData.append('username', email);
      formData.append('password', password);

      const response = await api.post('/auth/login', formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      const { access_token } = response.data;

      // Buscar dados do usuário após login bem sucedido
      localStorage.setItem('@Saira:token', access_token);
      localStorage.setItem('@Saira:auth_provider', 'local');
      api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;

      const userResponse = await api.get('/auth/me');
      const userData = userResponse.data;

      // Salvar dados do usuário
      localStorage.setItem('@Saira:user', JSON.stringify(userData));

      // Atualizar estado
      setUser(userData);
    } catch (error: any) {
      if (error.response?.status === 401) {
        throw new Error('Credenciais inválidas');
      }
      throw new Error('Erro ao fazer login. Tente novamente.');
    }
  }

  async function signInWithConecta(nextPath = '/dashboard') {
    try {
      const response = await api.get('/integrations/conecta/login-url', {
        params: { next: nextPath },
      });
      const authorizationUrl = response.data?.authorization_url;
      if (!authorizationUrl) {
        throw new Error('URL de autorização indisponível');
      }
      window.location.href = authorizationUrl;
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      throw new Error(detail || 'Não foi possível iniciar login com Conecta Recife');
    }
  }

  async function completeConectaLogin(ticket: string) {
    const response = await api.post('/integrations/conecta/exchange-ticket', { ticket });
    const { access_token } = response.data;

    localStorage.setItem('@Saira:token', access_token);
    localStorage.setItem('@Saira:auth_provider', 'conecta');
    api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;

    const userResponse = await api.get('/auth/me');
    const userData = userResponse.data;
    localStorage.setItem('@Saira:user', JSON.stringify(userData));
    setUser(userData);
  }

  async function signOut(options?: { global?: boolean }) {
    const authProvider = localStorage.getItem('@Saira:auth_provider');

    localStorage.removeItem('@Saira:token');
    localStorage.removeItem('@Saira:user');
    localStorage.removeItem('@Saira:auth_provider');
    delete api.defaults.headers.common['Authorization'];
    setUser(null);

    if (options?.global && authProvider === 'conecta') {
      try {
        const response = await api.get('/integrations/conecta/logout-url', {
          params: { redirect_uri: `${window.location.origin}/` },
        });
        const logoutUrl = response.data?.logout_url;
        if (logoutUrl) {
          window.location.href = logoutUrl;
          return;
        }
      } catch {
        // fallback local redirect below
      }
    }

    window.location.href = '/';
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        loading,
        signIn,
        signInWithConecta,
        completeConectaLogin,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }

  return context;
}
