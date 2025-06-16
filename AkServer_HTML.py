# --- HTML Content ---
LOGIN_FORM_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Login - AkServer</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background-color: #f4f4f4;
            margin: 0;
            min-height: 100vh;
        }}
        .header-logo {{
            display: block;
            margin: 10px auto 5px auto; /* top auto bottom auto */
            max-height: 40px; /* Adjust size as needed */
        }}
        h2 {{ text-align: center; }}

        .container {{
            background-color: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
            text-align: center;
            width: 350px;
            margin: 40px auto 0 auto;
        }}
        .otp-inputs {{
            display: flex;
            justify-content: space-between;
            margin: 20px 0 10px 0;
        }}
        .otp-inputs input {{
            width: 40px;
            height: 48px;
            font-size: 2rem;
            text-align: center;
            border: 1px solid #ddd;
            border-radius: 4px;
            outline: none;
            margin: 0 2px;
        }}
        .otp-inputs input:focus {{
            border-color: #007bff;
            box-shadow: 0 0 2px #007bff;
        }}
        button {{
            background-color: #007bff;
            color: white;
            padding: 10px 15px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }}
        button:hover {{ background-color: #0056b3; }}
        .message {{ margin-top: 15px; color: red; }}
    </style>
</head>
<body>
    <div class="container">
        <img src="/logo.png" alt="AkServer Logo" class="header-logo">
        <h2>AkServer Login</h2>
        <form id="otpForm" action="/login" method="post" autocomplete="off">
            <div class="otp-inputs">
                <input type="text" inputmode="numeric" pattern="[0-9]*" maxlength="1" name="otp1" required autocomplete="one-time-code">
                <input type="text" inputmode="numeric" pattern="[0-9]*" maxlength="1" name="otp2" required>
                <input type="text" inputmode="numeric" pattern="[0-9]*" maxlength="1" name="otp3" required>
                <input type="text" inputmode="numeric" pattern="[0-9]*" maxlength="1" name="otp4" required>
                <input type="text" inputmode="numeric" pattern="[0-9]*" maxlength="1" name="otp5" required>
                <input type="text" inputmode="numeric" pattern="[0-9]*" maxlength="1" name="otp6" required>
            </div>
            <input type="hidden" id="otp" name="otp">
            <button type="submit">Login</button>
        </form>
        {message_placeholder}
    </div>
    <script>
        // Focus handling and auto-move
        const inputs = document.querySelectorAll('.otp-inputs input');
        inputs[0].focus();
        inputs.forEach((input, idx) => {{
            input.addEventListener('input', function(e) {{
                this.value = this.value.replace(/[^0-9]/g, '');
                if (this.value && idx < inputs.length - 1) {{
                    inputs[idx + 1].focus();
                }}
                updateHiddenOtp();
            }});
            input.addEventListener('keydown', function(e) {{
                if (e.key === 'Backspace' && !this.value && idx > 0) {{
                    inputs[idx - 1].focus();
                }}
            }});
        }});
        function updateHiddenOtp() {{
            document.getElementById('otp').value = Array.from(inputs).map(i => i.value).join('');
        }}
        document.getElementById('otpForm').addEventListener('submit', function(e) {{
            updateHiddenOtp();
            if (document.getElementById('otp').value.length !== 6) {{
                e.preventDefault();
                alert('Please enter the 6-digit OTP.');
            }}
        }});
    </script>
    <div style="text-align: center; margin-top: 30px; font-size: 0.8em; color: #777;">
        © 2025 AkServer. All rights reserved.
    </div>
</body>
</html>
"""
UPLOAD_FORM_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>AkServer</title>
    <style>
        body {{ font-family: Arial, sans-serif; display: flex; flex-direction: column; align-items: center; background-color: #f4f4f4; margin: 20px; }}
        .header-logo {{
            display: block;
            margin: 0 auto 10px auto; /* Center and add some bottom margin */
            max-height: 40px; /* Adjust size as needed */
        }}
        h2 {{ text-align: center; }}
        .container {{ background-color: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); width: 90%; max-width: 600px; }}
        .nav-links {{ margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; width: 100%;}}
        .nav-links a {{ text-decoration: none; padding: 8px 12px; background-color: #17a2b8; color: white; border-radius: 4px; font-size: 0.9em; }}
        .nav-links a:hover {{ background-color: #138496; }}
        h2 {{ text-align: center; }}
        /* Style for the file input to make it look more like a button */
        .file-upload-label {{
            cursor: pointer; 
            display: block; 
            text-align: center; 
            padding: 10px 15px; 
            background-color: #28a745; 
            color: white; border-radius: 4px; 
            margin: 20px auto 10px auto; /* Adjusted margin */
            width: fit-content;
        }}
        .message {{ margin-top: 15px; text-align: center; }}
        .trial-status {{ text-align: center; font-size: 0.85em; padding: 5px; margin-bottom: 10px; border-radius: 3px; }}
        .trial-active {{ background-color: #e6ffed; color: #28a745; border: 1px solid #c3e6cb; }}
        .trial-expired {{ background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
        .trial-unavailable {{ background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; }}

        .logout-link {{ display: block; text-align: right; margin-bottom: 10px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="/view_files">View Uploaded Files</a>
            {logout_placeholder}
        </div>
        <img src="/logo.png" alt="AkServer Logo" class="header-logo">
        <h2>AkServer</h2>
        {trial_message_placeholder}
        <form id="uploadForm" method="post" enctype="multipart/form-data">
            <label for="fileUploadInput" class="file-upload-label">
                Choose Folder to Sync
            </label>
            <input type="file" id="fileUploadInput" name="files[]" multiple webkitdirectory directory style="display: none;">
            <!-- Sync button and folderSelectionInfo div are removed for automatic upload -->
        </form>
        <div class="message" id="uploadMessage">{message_placeholder}</div>
        <div style="text-align: center; margin-top: 20px; font-size: 0.8em;">
            <a href="https://forms.gle/mWgUnNddhLbAyg3x8" target="_blank" style="color: #007bff; text-decoration: none;">Provide Feedback</a>
        </div>
    </div>
    <script>
        const uploadForm = document.getElementById('uploadForm');
        const fileInput = document.getElementById('fileUploadInput');
        const messageDiv = document.getElementById('uploadMessage');

        function performUpload() {{
            if (fileInput.files.length === 0) {{
                // Optionally, provide feedback if no files are selected, or just return.
                // For example:
                // messageDiv.textContent = 'No folder selected or folder is empty.';
                // messageDiv.style.color = 'orange';
                return; 
            }}


            messageDiv.textContent = 'Syncing...';
            messageDiv.style.color = 'blue';
            
            const formData = new FormData(uploadForm); // Pass the form element

            fetch('/upload', {{ // The URL path for uploads
                method: 'POST',
                body: formData
            }})
            .then(response => {{
                if (!response.ok) {{ // Check for HTTP errors (4xx, 5xx)
                    return response.json()
                        .catch(() => {{ // If response body is not JSON or parsing fails
                            throw new Error(`Server error: $\{{response.status}} $\{{response.statusText}}`);
                        }});
                }}
                return response.json(); // If response.ok, parse JSON
            }})
            .then(data => {{
                // Check if data itself indicates success, which is expected for a successful JSON response
                // This 'data' object comes from response.json()
                if(data && data.success) {{ 
                    messageDiv.textContent = data.message + (data.files ? ' Files: ' + data.files.join(', ') : '');
                    messageDiv.style.color = 'green';
                }} else {{
                    messageDiv.textContent = 'Error: ' + data.message; // Server-side logical error
                    messageDiv.style.color = 'red';
                }}
                uploadForm.reset(); // Resets the file input
            }})
            .catch(error => {{
                messageDiv.textContent = 'Sync failed or cancelled: ' + error.message;
                messageDiv.style.color = 'red';
                uploadForm.reset(); // Reset on error too, so user can try again
            }});
        }}

        // Listen for changes on the file input (i.e., when a folder is selected)
        // and immediately attempt to upload.
        fileInput.addEventListener('change', performUpload);
    </script>
    <div style="text-align: center; margin-top: 30px; font-size: 0.8em; color: #777;">
        © 2025 AkServer. All rights reserved.
    </div>
</body>
</html>
"""
VIEW_FILES_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>View Uploaded Files - AkServer</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ 
            font-family: Arial, sans-serif; 
            margin: 0; 
            background-color: #f0f0f0; /* Lightest gray for overall page background */
        }}
        .header-logo-container {{ /* For view_files, to place logo inside nav bar */
            text-align: center;
            padding-bottom: 10px;
        }}
        .header-logo {{ max-height: 30px; }} /* Slightly smaller for this page */
        .container {{ 
            background-color: #fff; /* White background for the main content block */
            width: 100%; 
            max-width: none; /* Ensure it can take full screen width */
            min-height: 100vh; /* Ensure container fills viewport height */
            margin: 0;
            padding: 0;
        }}
        h2.gallery-title {{ 
            text-align: center; 
            padding: 15px 10px; 
            margin: 0; 
            font-size: 1.2em;
            background-color: #f8f9fa; 
            border-bottom: 1px solid #dee2e6; 
            color: #333;
        }}

        /* Styles for the top navigation bar area */
        .navigation-bar {{
            padding: 10px 15px;
            background-color: #fff; /* Match container or a distinct nav color */
            border-bottom: 1px solid #e0e0e0;
        }}
        .nav-links {{ margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;}}
        .back-link {{ text-decoration: none; padding: 8px 12px; background-color: #6c757d; color: white; border-radius: 4px; }}
        .back-link:hover {{ background-color: #5a6268; }}
        .logout-link {{ text-decoration: none; padding: 8px 12px; background-color: #dc3545; color: white; border-radius: 4px; }}
        .logout-link:hover {{ background-color: #c82333; }}

        .file-list {{
            list-style-type: none;
            padding: 5px; /* Small padding around the grid itself */
            margin: 0; /* Remove default ul margin */
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); /* Key for responsive tiles */
            gap: 5px; /* Small gap between tiles */
        }}

        .file-item {{
            background-color: #f9f9f9; /* Light background for each tile */
            border-radius: 0px; /* Sharp, square corners for tiles */
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        .file-item .media-container {{
            width: 100%;
            padding-bottom: 100%; /* This creates a 1:1 aspect ratio (square) for the media area */
            position: relative; /* Crucial for positioning the img/video inside */
            overflow: hidden;
            background-color: #e0e0e0; /* Placeholder background if media is missing or for non-media */
        }}
        .file-item .media-container img,
        .file-item .media-container video {{
            position: absolute; /* Position img/video within the square media-container */
            top: 0; 
            left: 0; 
            width: 100%; 
            height: 100%;
            object-fit: cover; /* Makes media fill the container, cropping if necessary */
            display: block;
        }}
        .file-item .file-name-link {{
            font-weight: 500; /* Normal bold */
            color: #333;
            text-decoration: none;
            padding: 6px 8px; /* Compact padding for the filename */
            text-align: center;
            font-size: 0.75em; /* Smaller font for filename to fit compact tiles */
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            display: block;
            background-color: #fff; /* Filename area background, distinct from media item bg */
        }}
        .file-item .file-name-link:hover {{
            color: #007bff;
            text-decoration: underline;
        }}
        .file-item .no-preview {{
            font-style: italic;
            color: #6c757d;
            text-align: center;
            padding: 10px; /* Padding inside the no-preview box */
            font-size: 0.9em;
            width: 100%;
            height: 100%; /* Fill media-container */
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .message {{ margin-top: 15px; text-align: center; padding: 10px; border-radius: 4px; }}
        .message.error {{ background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
        .message.info {{ background-color: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }}
    </style>
    <style> /* Duplicating trial status styles here for self-containment, or use a shared CSS */
        .trial-status {{ text-align: center; font-size: 0.85em; padding: 5px; margin: 0 15px 10px 15px; border-radius: 3px; }}
        .trial-active {{ background-color: #e6ffed; color: #28a745; border: 1px solid #c3e6cb; }}
        .trial-expired {{ background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
        .trial-unavailable {{ background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="navigation-bar">
            <div class="nav-links"> <!-- Kept original nav-links structure inside the new bar -->
                <a href="/" class="back-link">&larr; Back to Upload</a>
                {logout_placeholder}
            </div>
            <div class="header-logo-container">
                <img src="/logo.png" alt="AkServer Logo" class="header-logo">
            </div>
        </div>
        <h2 class="gallery-title">Uploaded Files</h2>
        {trial_message_placeholder}
        {message_placeholder}
        <ul class="file-list">
            {file_list_items}
        </ul>
        <div style="text-align: center; padding: 10px 0; font-size: 0.8em;">
            <a href="https://forms.gle/mmATvTDQi6mBqA1x9" target="_blank" style="color: #007bff; text-decoration: none;">Provide Feedback</a>
        </div>
        <div style="text-align: center; padding-bottom: 10px; font-size: 0.8em; color: #777;">
            © 2025 AkServer. All rights reserved.
        </div>
    </div>
</body>
</html>
"""
DEVICE_NAME_FORM_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Register Device - AkServer</title>
    <style>
        body {{ font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; min-height: 100vh; }}
        .header-logo {{
            display: block;
            margin: 10px auto 5px auto;
            max-height: 40px; /* Adjust size as needed */
        }}
        h2 {{ text-align: center; }}
        .container {{ background-color: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); text-align: center; width: 350px; margin: 40px auto 0 auto; }}
        input[type="text"] {{ padding: 10px; margin-bottom: 20px; width: calc(100% - 22px); border: 1px solid #ddd; border-radius: 4px; }}
        button {{ background-color: #007bff; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; }}
        button:hover {{ background-color: #0056b3; }}
        .message {{ margin-top: 15px; color: red; }}
    </style>
</head><body>
    <div class="container">
        <h2>Register Your Device</h2>
        <img src="/logo.png" alt="AkServer Logo" class="header-logo">
        <p>Please enter a name for this device. This name will help you identify it later.</p>
        <form action="/submit_device_name" method="post" autocomplete="off">
            <input type="text" name="device_name" placeholder="Enter Device Name (e.g., My Phone)" maxlength="50" required autofocus><br>
            <button type="submit">Save Device Name</button>
        </form>
        {message_placeholder}
        <div style="text-align: center; margin-top: 30px; font-size: 0.8em; color: #777;">
            © 2025 AkServer. All rights reserved.
        </div>
    </div>
</body></html>
"""