import { useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './pages/LoginPage';
import { BuyerDashboard } from './pages/BuyerDashboard';
import { SharedBriefPage } from './pages/SharedBriefPage';

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

/** Seller desk is paused — always land on buyer and normalize role. */
function BuyerOnly({ children }: { children: React.ReactNode }) {
  const { user, loading, chooseRole } = useAuth();

  useEffect(() => {
    if (loading || !user) return;
    if (user.role !== 'buyer') {
      void chooseRole('buyer').catch(() => {
        /* ignore — still show buyer UI */
      });
    }
  }, [user, loading, chooseRole]);

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
  return <>{children}</>;
}

function HomeRedirect() {
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
  return <Navigate to="/buyer" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/b/:token" element={<SharedBriefPage />} />
        <Route
          path="/buyer"
          element={
            <ProtectedRoute>
              <BuyerOnly>
                <BuyerDashboard />
              </BuyerOnly>
            </ProtectedRoute>
          }
        />
        {/* Seller dashboard paused — keep URLs from 404ing */}
        <Route path="/business" element={<Navigate to="/buyer" replace />} />
        <Route path="/role" element={<Navigate to="/buyer" replace />} />
        <Route path="/" element={<HomeRedirect />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
