import React, { useState, useCallback, useRef, useEffect } from "react";
import ReactWebcam from "react-webcam";
import axios from "axios";
import { message } from "antd";
import "../styles/CreateDataset.css";

const MIN_IMAGES = 5; // Minimum images required per student for good accuracy

const CreateDataset = ({ classId, classname }) => {
  const [name, setName] = useState("");
  const [rollNumber, setRollNumber] = useState("");
  const [email, setEmail] = useState("");
  const [cameraOn, setCameraOn] = useState(false);
  const [imageCount, setImageCount] = useState(0);
  const [students, setStudents] = useState([]);
  const [fetchingStudents, setFetchingStudents] = useState(false);
  const [isStudentAdded, setIsStudentAdded] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const webcamRef = useRef(null);

  const videoConstraints = {
    width: 640,
    height: 480,
    facingMode: "user",
  };

  useEffect(() => {
    fetchStudents();
  }, []);

  const fetchStudents = async () => {
    try {
      setFetchingStudents(true);
      const response = await axios.post(
        "http://localhost:5000/api/user/student/getstudents",
        { classid: classId }
      );
      if (Array.isArray(response.data)) {
        setStudents(response.data);
      }
    } catch (error) {
      console.error("Error fetching students", error);
    } finally {
      setFetchingStudents(false);
    }
  };

  const toggleWebcam = () => {
    const newCameraState = !cameraOn;
    setCameraOn(newCameraState);
    if (!newCameraState) {
      // Reset form when camera is turned off
      setName("");
      setRollNumber("");
      setEmail("");
      setImageCount(0);
      setIsStudentAdded(false);
    }
  };

  const capture = useCallback(async () => {
    if (!name || !rollNumber || !email) {
      message.warning("Please fill in Name, Roll Number, and Email before capturing.");
      return;
    }

    const imageSrc = webcamRef.current.getScreenshot();
    if (!imageSrc) return;

    setCapturing(true);
    try {
      // Send image to Flask/DeepFace server for dataset creation
      const response = await axios.post(
        "http://127.0.0.1:8000/api/createdataset/",
        {
          name,
          roll_number: rollNumber,
          email,
          classroom_name: classname,
          image: imageSrc,
        }
      );

      const totalImages = response.data.total_images;
      setImageCount(totalImages);

      // After minimum images captured, add student to Node.js database (only once)
      if (totalImages >= MIN_IMAGES && !isStudentAdded) {
        try {
          await axios.post(
            "http://localhost:5000/api/user/student/addstudent",
            {
              name,
              roll_number: rollNumber,
              email,
              classid: classId,
            }
          );
          setIsStudentAdded(true);
          message.success(`Student "${name}" enrolled successfully with ${totalImages} images!`);
          fetchStudents();
        } catch (addError) {
          // Student might already exist in DB — that's OK, just keep capturing images
          if (addError.response && addError.response.status === 400) {
            setIsStudentAdded(true);
            message.info("Student already enrolled. Additional images saved for better accuracy.");
          } else {
            console.error("Error adding student:", addError);
          }
        }
      } else if (totalImages < MIN_IMAGES) {
        message.info(`Image ${totalImages}/${MIN_IMAGES} captured. Keep capturing!`);
      } else {
        message.success("Additional image saved for better accuracy.");
      }
    } catch (error) {
      console.error("Error sending image to backend", error);
      message.error("Failed to save image. Is the Face Recognition server running on port 8000?");
    } finally {
      setCapturing(false);
    }
  }, [webcamRef, name, rollNumber, email, classname, classId, isStudentAdded]);

  const progress = Math.min((imageCount / MIN_IMAGES) * 100, 100);

  return (
    <div className="create-dataset-container">
      <div className="students-list ml-48">
        <h2>Students in this class:</h2>
        <ul>
          {students.map((student) => (
            <li key={student._id}>
              {student.name} - {student.roll_number}
            </li>
          ))}
        </ul>
        {fetchingStudents && <p>Loading students...</p>}
      </div>
      <div className="form-container">
        <h1 className="main-heading text-3xl">Create Dataset</h1>

        <div>
          <label>Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Enter student name"
            disabled={cameraOn && imageCount > 0}
          />
        </div>
        <div>
          <label>Roll Number</label>
          <input
            type="text"
            value={rollNumber}
            onChange={(e) => setRollNumber(e.target.value)}
            placeholder="Enter roll number"
            disabled={cameraOn && imageCount > 0}
          />
        </div>
        <div>
          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Enter student email"
            disabled={cameraOn && imageCount > 0}
          />
        </div>

        <div>
          <button onClick={toggleWebcam} className="btn">
            {cameraOn ? "Turn Off Camera" : "Start Capture"}
          </button>
        </div>
        {cameraOn && (
          <div className="webcam-container">
            <ReactWebcam
              audio={false}
              height={480}
              screenshotFormat="image/jpeg"
              width={640}
              videoConstraints={videoConstraints}
              ref={webcamRef}
            />
            <button
              onClick={capture}
              className="capture-btn"
              disabled={capturing}
            >
              {capturing ? "Saving..." : "Capture Photo"}
            </button>

            {/* Progress indicator */}
            {imageCount > 0 && (
              <div style={{ marginTop: "10px", width: "100%" }}>
                <div
                  style={{
                    background: "#333",
                    borderRadius: "8px",
                    overflow: "hidden",
                    height: "24px",
                    width: "100%",
                  }}
                >
                  <div
                    style={{
                      background: progress >= 100 ? "#22c55e" : "#3b82f6",
                      height: "100%",
                      width: `${progress}%`,
                      transition: "width 0.3s ease",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "white",
                      fontSize: "12px",
                      fontWeight: "bold",
                    }}
                  >
                    {imageCount}/{MIN_IMAGES} images
                  </div>
                </div>
                <p style={{ color: "#aaa", fontSize: "13px", marginTop: "5px" }}>
                  {imageCount < MIN_IMAGES
                    ? `Capture ${MIN_IMAGES - imageCount} more image(s) to enroll this student.`
                    : "✅ Student enrolled! You can capture more images for better accuracy."}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default CreateDataset;
