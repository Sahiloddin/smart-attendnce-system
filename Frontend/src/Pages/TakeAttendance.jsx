import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";

const TakeAttendance = () => {
  const navigate = useNavigate();

  useEffect(() => {
    // Redirect to the classroom-based attendance flow
    navigate("/yourclassroom", { replace: true });
  }, [navigate]);

  return (
    <div className="container mx-auto p-4 flex flex-col items-center mt-40">
      <p className="text-white text-lg">Redirecting to your classrooms...</p>
    </div>
  );
};

export default TakeAttendance;

