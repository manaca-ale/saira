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
  signOut: () => void;
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

  function signOut() {
    localStorage.removeItem('@Saira:token');
    localStorage.removeItem('@Saira:user');
    delete api.defaults.headers.common['Authorization'];
    setUser(null);
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        loading,
        signIn,
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
