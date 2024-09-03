frappe.ui.form.on('Get Printers', {
    printers: function(frm) {
        // Define the API endpoint
        const apiEndpoint = 'http://192.168.1.7:5000/get_printers';

        // Fetch printers from the API
        fetch(apiEndpoint)
            .then(response => response.json())
            .then(data => {
                // Check if data is an array of printers
                console.log(data)
            })
            .catch(error => {
                console.error('Error fetching printers:', error);
				frappe.msgprint("Check if local app is up")
            });
    }
});
