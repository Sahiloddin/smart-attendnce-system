import React, { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";
import { API_BASE, FACE_API_BASE } from "../config/api";
import "../styles/ClassRoomDetails.css";
import "../styles/TrainModel.css";
import CreateDataset from "../components/CreateDataset";

const ClassRoomDetails = () => {
  const { id } = useParams();
  const [classroom, setClassroom] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Train model state
  const [trainStatus, setTrainStatus] = useState("idle");
  const [trainMessage, setTrainMessage] = useState("");

  useEffect(() => {
    const fetchClassroomDetails = async () => {
      try {
        const response = await axios.post(
          `${API_BASE}/api/user/getclass`,
          { id },
          {
            headers: {
              "Content-Type": "application/json",
            },
          }
        );
        setClassroom(response.data.classroom);
        setLoading(false);
      } catch (error) {
        setError(error.message);
        setLoading(false);
      }
    };

    fetchClassroomDetails();
  }, [id]);

  const handleTrainModel = async () => {
    if (!classroom?.classname) return;

    setTrainStatus("loading");
    setTrainMessage("Training model... Please wait.");

    try {
      const response = await axios.post(`${FACE_API_BASE}/api/retrainmodel/`, {
        classroom_name: classroom.classname,
      });
      setTrainStatus("success");
      setTrainMessage(
        `✅ Model trained! ${response.data.students_count || ""} student(s) indexed.`
      );
    } catch (error) {
      console.error("Error training model:", error);
      setTrainStatus("error");
      const errMsg =
        error.response?.data?.error ||
        "Failed to train model. Is the Face Recognition server running on port 8000?";
      setTrainMessage(`❌ ${errMsg}`);
    }
  };

  if (loading) {
    return <div className="container">Loading...</div>;
  }

  if (error) {
    return <div className="container">Error: {error}</div>;
  }

  return (
    <>
      <div className="container">
        <div className="details-card text-white flex ">
          <p>
            <strong>Classname:</strong> {classroom.classname}
          </p>
          <p>
            <strong>Department:</strong> {classroom.department}
          </p>
          <p>
            <strong>Subject:</strong> {classroom.subject}
          </p>
        </div>

        {/* Train Model Section */}
        <div className="train-model-section" style={{ marginTop: "24px" }}>
          <button
            onClick={handleTrainModel}
            disabled={trainStatus === "loading"}
            className={`train-model-btn ${trainStatus === "loading" ? "training" : ""}`}
          >
            {trainStatus === "loading"
              ? "⏳ Training..."
              : trainStatus === "success"
                ? "🔄 Retrain Model"
                : "🧠 Train Model"}
          </button>
          <span className={`train-status ${trainStatus}`}>
            {trainStatus === "idle"
              ? "After adding students, click to train the face recognition model"
              : trainMessage}
          </span>
        </div>

        {/* Take Attendance Link */}
        {trainStatus === "success" && (
          <div style={{ marginTop: "16px" }}>
            <Link to={`/yourclassroom/takeattendance/${id}`}>
              <button className="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 transition duration-200">
                📷 Go Take Attendance
              </button>
            </Link>
          </div>
        )}
      </div>
      <div>
        <CreateDataset classId={id} classname={classroom.classname} />
      </div>
    </>
  );
};

export default ClassRoomDetails;

