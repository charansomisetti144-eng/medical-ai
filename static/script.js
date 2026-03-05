const container = document.getElementById("container");

const loginBtn = document.getElementById("loginBtn");
const signupBtn = document.getElementById("signupBtn");
const createBtn = document.querySelector(".signup button");


// Manual switch to login
loginBtn.onclick = () => {

    container.classList.add("login-active");

};


// Manual switch back to signup
signupBtn.onclick = () => {

    container.classList.remove("login-active");

};


// After clicking Create Account
createBtn.onclick = () => {

    setTimeout(() => {

        container.classList.add("login-active");

    }, 600);

};