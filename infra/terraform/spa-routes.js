// CloudFront Function (viewer request) for the site's default behavior: the React app's
// client-side routes (/agents/house-smart, /episodes/<id>) have no file of their own, so they
// get the SPA shell. Paths with an extension (/assets/index-1a2b.js, /favicon.svg) pass through.
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  var last = uri.substring(uri.lastIndexOf("/") + 1);
  if (last.indexOf(".") === -1) {
    request.uri = "/index.html";
  }
  return request;
}
