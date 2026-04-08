import { NavLink, Link } from "react-router-dom";
import "../styles/Navbar.css";
import { useContext } from "react";
import { usercontext } from "../context/user-context";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faUser } from "@fortawesome/free-solid-svg-icons";

export const Navbar = () => {
  const { user, setUser } = useContext(usercontext);

  const handleLogout = () => {
    localStorage.removeItem("token");
    setUser({ name: "", email: "" });
  };

  return (
    <>
      <header>
        <div className="navbar">
          <div className="container nav">
            <nav>
              <ul>
                <li>
                  <NavLink
                    to="/"
                    className={({ isActive }) => isActive ? "active" : ""}
                  >
                    Home
                  </NavLink>
                </li>

                {user.name && (
                  <>
                    <li>
                      <NavLink
                        to="/yourclassroom"
                        className={({ isActive }) => isActive ? "active" : ""}
                      >
                        Your Classroom
                      </NavLink>
                    </li>
                    <li>
                      <NavLink
                        to="/createclassroom"
                        className={({ isActive }) => isActive ? "active" : ""}
                      >
                        Create Classroom
                      </NavLink>
                    </li>
                  </>
                )}

                {!user.name ? (
                  <>
                    <li>
                      <NavLink
                        to="/login"
                        className={({ isActive }) => isActive ? "active" : ""}
                      >
                        Login
                      </NavLink>
                    </li>
                    <li>
                      <NavLink
                        to="/register"
                        className={({ isActive }) => isActive ? "active" : ""}
                      >
                        Register
                      </NavLink>
                    </li>
                  </>
                ) : (
                  <li>
                    <Link to="/" onClick={handleLogout}>
                      Logout
                    </Link>
                  </li>
                )}
              </ul>
            </nav>
            <div className="text-white">
              {user.name ? (
                <Link to="/" className="username">
                  <div>
                    <FontAwesomeIcon icon={faUser} style={{ color: "white" }} />
                    &nbsp;&nbsp;
                    {user.name}
                  </div>
                </Link>
              ) : (
                <Link to="/">Smart Attendance System</Link>
              )}
            </div>
          </div>
        </div>
      </header>
    </>
  );
};
