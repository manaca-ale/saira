import React, { useState } from "react";
import {
  LayoutDashboard,
  Cctv,
  Users,
  Settings,
  LogOut,
  History,
} from "lucide-react"; // Added History
import { useNavigate, useLocation } from "react-router-dom";

export const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  // --- Modal State ---
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [isClosing, setIsClosing] = useState(false);

  const menuItems = [
    { icon: LayoutDashboard, path: "/dashboard" },
    { icon: History, path: "/history" }, // NEW: History Page Link
    { icon: Cctv, path: "/detections" },
    { icon: Users, path: "/users" },
  ];

  const handleLogoutClick = () => {
    setShowLogoutConfirm(true);
  };

  const closeModal = () => {
    setIsClosing(true);
    setTimeout(() => {
      setShowLogoutConfirm(false);
      setIsClosing(false);
    }, 500);
  };

  const confirmLogout = () => {
    navigate("/");
  };

  return (
    <>
      <style>{`
        @keyframes modalPop {
          0% { opacity: 0; transform: scale(0.8) translateY(50px); }
          100% { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes modalPopExit {
          0% { opacity: 1; transform: scale(1) translateY(0); }
          100% { opacity: 0; transform: scale(0.8) translateY(50px); }
        }
      `}</style>

      <div className="h-full w-20 bg-[#1a1a1a] flex flex-col items-center py-6 absolute left-0 top-0 z-40 border-r border-gray-800">
        <nav className="flex-1 flex flex-col justify-center gap-8 w-full">
          {menuItems.map((item, index) => {
            const isActive = location.pathname === item.path;
            return (
              <button
                key={index}
                onClick={() => navigate(item.path)}
                className={`relative w-full h-12 flex items-center justify-center transition-colors group
                            ${isActive ? "text-[#d9f99d]" : "text-gray-500 hover:text-gray-300"}
                        `}
              >
                {isActive && (
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-[#d9f99d] rounded-r-md shadow-[0_0_10px_#d9f99d]" />
                )}
                <item.icon strokeWidth={2} size={24} />
              </button>
            );
          })}
        </nav>

        <div className="flex flex-col gap-6 w-full items-center mb-4">
          <button className="text-gray-500 hover:text-white transition-colors">
            <Settings size={24} />
          </button>
          <div className="w-10 h-10 rounded-full bg-gray-700 overflow-hidden border-2 border-transparent hover:border-[#d9f99d] transition-all cursor-pointer">
            <img
              src="https://i.pravatar.cc/150?u=admin"
              alt="User"
              className="w-full h-full object-cover"
            />
          </div>
          <button
            onClick={handleLogoutClick}
            className="text-gray-500 hover:text-red-500 transition-colors mt-2"
          >
            <LogOut size={20} />
          </button>
        </div>
      </div>

      {showLogoutConfirm && (
        <div
          className={`
                fixed inset-0 z-[10000] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 
                transition-opacity duration-500 
                ${isClosing ? "opacity-0" : "opacity-100"}
            `}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 relative"
            style={{
              animation: isClosing
                ? "modalPopExit 0.5s ease-in forwards"
                : "modalPop 0.5s ease-out forwards",
            }}
          >
            <h3 className="text-lg font-bold text-[#1a1a1a] mb-2 select-none">
              Deseja realmente sair?
            </h3>
            <p className="text-gray-500 text-sm mb-6 select-none">
              Você precisará fazer login novamente para acessar o sistema.
            </p>
            <div className="flex items-center justify-end gap-3">
              <button
                onClick={closeModal}
                className="px-4 py-2 text-sm font-bold text-gray-500 hover:bg-gray-100 rounded-lg transition-colors select-none"
              >
                Cancelar
              </button>
              <button
                onClick={confirmLogout}
                className="px-4 py-2 text-sm font-bold text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors shadow-lg shadow-red-200 select-none"
              >
                Sair
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
