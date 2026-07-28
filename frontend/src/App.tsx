import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './pages/LoginPage';
import { RoleSelectPage } from './pages/RoleSelectPage';
import { BusinessDashboard } from './pages/BusinessDashboard';
import { BuyerDashboard } from './pages/BuyerDashboard';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth();
  if (loading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center text-sm font-medium"
        style={{
          background: 'linear-gradient(165deg, #f4f7ff 0%, #fff8f0 100%)',
          color: '#3d4f6f',
          fontFamily: "'DM Sans', system-ui, sans-serif",
        }}
      >
        Opening…
      </div>
    );
  }
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RoleGate({ role, children }: { role: 'business' | 'buyer'; children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user?.role) return <Navigate to="/role" replace />;
  if (user.role !== role) return <Navigate to={user.role === 'business' ? '/business' : '/buyer'} replace />;
  return <>{children}</>;
}

function HomeRedirect() {
  const { token, user, loading } = useAuth();
  if (loading) return null;
  if (!token) return <Navigate to="/login" replace />;
  if (!user?.role) return <Navigate to="/role" replace />;
  return <Navigate to={user.role === 'business' ? '/business' : '/buyer'} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/role"
          element={
            <ProtectedRoute>
              <RoleSelectPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/business"
          element={
            <ProtectedRoute>
              <RoleGate role="business">
                <BusinessDashboard />
              </RoleGate>
            </ProtectedRoute>
          }
        />
        <Route
          path="/buyer"
          element={
            <ProtectedRoute>
              <RoleGate role="buyer">
                <BuyerDashboard />
              </RoleGate>
            </ProtectedRoute>
          }
        />
        <Route path="/" element={<HomeRedirect />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
