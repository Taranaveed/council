import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { fetchMe, login as apiLogin, register as apiRegister, setRole as apiSetRole, type User } from '../lib/api';

type AuthContextValue = {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, password: string) => Promise<User>;
  chooseRole: (role: 'business' | 'buyer') => Promise<User>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('sf_token'));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    fetchMe()
      .then((u) => setUser(u))
      .catch(() => {
        localStorage.removeItem('sf_token');
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, [token]);

  const persist = (accessToken: string, nextUser: User) => {
    localStorage.setItem('sf_token', accessToken);
    setToken(accessToken);
    setUser(nextUser);
  };

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiLogin(email, password);
    persist(res.access_token, res.user);
    return res.user;
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const res = await apiRegister(email, password);
    persist(res.access_token, res.user);
    return res.user;
  }, []);

  const chooseRole = useCallback(async (role: 'business' | 'buyer') => {
    const next = await apiSetRole(role);
    setUser(next);
    return next;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('sf_token');
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, token, loading, login, register, chooseRole, logout }),
    [user, token, loading, login, register, chooseRole, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
