import React from "react";
import { LayoutDashboard, Map, Users, Settings, LogOut } from "lucide-react";
import { useNavigate, useLocation } from "react-router-dom";

export const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    { icon: LayoutDashboard, path: "/dashboard" },
    { icon: Map, path: "/detections" },
    { icon: Users, path: "/users" },
  ];

  const handleLogout = () => {
    navigate("/");
  };

  return (
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
      {/* Bottom Actions remain the same */}
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
          onClick={handleLogout}
          className="text-gray-500 hover:text-red-500 transition-colors mt-2"
        >
          <LogOut size={20} />
        </button>
      </div>
    </div>
  );
};
