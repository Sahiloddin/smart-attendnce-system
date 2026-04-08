const mongoose = require("mongoose");
require("dotenv").config();

const URI = process.env.MONGO_URI;
console.log(URI);

const connectDb = async () => {
  try {
    await mongoose.connect(URI);
    console.log("connection successful to DB");
  } catch (error) {
    console.error("database connection fail");
    process.exit(1);
  }
};

module.exports = connectDb;
